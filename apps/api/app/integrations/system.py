from contextlib import suppress
from datetime import UTC, datetime
from importlib.metadata import version
from itertools import islice
from math import isfinite
from os import getloadavg
from pathlib import Path
from platform import machine, python_version, release
from re import fullmatch
from time import time

import psutil

from app.core.config import Settings
from app.integrations.base import Integration, IntegrationError
from app.schemas.integrations import IntegrationHealth, ResourceUsage, SystemSummary
from app.schemas.system import (
    Compute,
    Identity,
    Memory,
    Sensors,
    Storage,
    SystemInformation,
    Temperature,
)

COLLECTION_ERRORS = (OSError, RuntimeError, ValueError, AttributeError, psutil.Error)
_DRM_ROOT = Path("/sys/class/drm")
_NVIDIA_GPU_ROOT = Path("/proc/driver/nvidia/gpus")
_GPU_VENDORS = {"10de": "NVIDIA", "1002": "AMD", "8086": "Intel"}


def _usage(total: int, used: int, available: int, percent: float) -> ResourceUsage:
    return ResourceUsage(
        total_bytes=max(0, total),
        used_bytes=max(0, used),
        available_bytes=max(0, available),
        percent=min(100, max(0, percent)),
    )


def _cpu_model() -> str | None:
    # Read only the kernel's fixed CPU-info interface; never inspect arbitrary paths.
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as cpuinfo:
            for line in cpuinfo.read(65_536).splitlines():
                if line.startswith("model name") and ":" in line:
                    return line.split(":", 1)[1].strip()[:120] or None
    except OSError:
        return None
    return None


def _read_kernel_text(path: Path, limit: int) -> str | None:
    try:
        with path.open(encoding="utf-8", errors="replace") as source:
            return source.read(limit)
    except OSError:
        return None


def _detected_gpus() -> list[str]:
    """Report DRM-visible PCI devices, optionally enriched by a matching NVIDIA driver label."""
    detected: list[str] = []
    try:
        for card in islice(_DRM_ROOT.glob("card[0-9]*"), 64):
            if not fullmatch(r"card\d+", card.name):
                continue  # Exclude connector entries such as card1-HDMI-A-1.
            vendor = (_read_kernel_text(card / "device/vendor", 32) or "").strip()
            device = (_read_kernel_text(card / "device/device", 32) or "").strip()
            vendor, device = vendor.removeprefix("0x"), device.removeprefix("0x")
            if not fullmatch(r"[0-9a-fA-F]{4}", vendor) or not fullmatch(r"[0-9a-fA-F]{4}", device):
                continue
            vendor, device = vendor.lower(), device.lower()
            brand = _GPU_VENDORS.get(vendor)
            name = (
                f"{brand} GPU (PCI {vendor}:{device})" if brand else f"GPU (PCI {vendor}:{device})"
            )
            if vendor == "10de":
                uevent = _read_kernel_text(card / "device/uevent", 4096) or ""
                for line in uevent.splitlines():
                    if not line.startswith("PCI_SLOT_NAME="):
                        continue
                    slot = line.partition("=")[2]
                    if not fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]", slot):
                        break
                    information = _read_kernel_text(_NVIDIA_GPU_ROOT / slot / "information", 4096)
                    for field in (information or "").splitlines():
                        if field.startswith("Model:"):
                            model = field.partition(":")[2].strip()[:120]
                            if model:
                                name = model
                            break
                    break
            detected.append(name)
            if len(detected) >= 8:
                break
    except OSError:
        pass
    return detected


def _temperature_label(group: str, raw_label: str, index: int) -> str:
    label = raw_label.strip().lower()
    kind = group.lower()
    if label.startswith("package id ") and label[11:].isdigit():
        return f"CPU package {label[11:]}"
    if label.startswith("core ") and label[5:].isdigit() and kind in {"coretemp", "k10temp"}:
        return f"CPU core {label[5:]}"
    if kind == "acpitz":
        return f"ACPI thermal zone {index}"
    if kind == "jc42":
        return f"Memory module {index}"
    if kind == "asusec":
        board_sensors = {
            "chipset": "Motherboard chipset",
            "cpu": "Motherboard CPU sensor",
            "motherboard": "Motherboard sensor",
            "t_sensor": "External sensor header",
            "vrm": "Voltage regulator (VRM)",
        }
        if label in board_sensors:
            return board_sensors[label]
    if kind in {"coretemp", "k10temp"}:
        return f"CPU temperature sensor {index}"
    if kind == "nvme":
        return f"NVMe drive sensor {index}"
    if kind == "amdgpu":
        return f"GPU temperature sensor {index}"
    return "Other temperature sensor"


class SystemIntegration(Integration):
    integration_id = "system"
    name = "Ark system"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def summary(self) -> SystemSummary:
        try:
            memory = psutil.virtual_memory()
            storage = psutil.disk_usage(self._settings.system_storage_path)
            return SystemSummary(
                hostname=self._settings.system_hostname,
                os=self._settings.system_os_name,
                kernel=release(),
                uptime_seconds=max(0, int(time() - psutil.boot_time())),
                cpu_percent=psutil.cpu_percent(interval=0.1),
                cpu_count=psutil.cpu_count() or 1,
                memory=ResourceUsage(
                    total_bytes=memory.total,
                    used_bytes=memory.total - memory.available,
                    available_bytes=memory.available,
                    percent=memory.percent,
                ),
                storage=ResourceUsage(
                    total_bytes=storage.total,
                    used_bytes=storage.used,
                    available_bytes=storage.free,
                    percent=storage.percent,
                ),
                storage_path=self._settings.system_storage_path,
                collected_at=datetime.now(UTC),
            )
        except (OSError, RuntimeError) as error:
            raise IntegrationError("System metrics are unavailable.") from error

    def health_for(self, summary: SystemSummary) -> IntegrationHealth:
        constrained_resources = []
        if summary.memory.percent >= 95:
            constrained_resources.append("memory")
        if summary.storage.percent >= 90:
            constrained_resources.append("storage")

        if constrained_resources:
            return IntegrationHealth(
                id=self.integration_id,
                name=self.name,
                state="degraded",
                message=f"High {' and '.join(constrained_resources)} utilization.",
                checked_at=summary.collected_at,
            )
        return IntegrationHealth(
            id=self.integration_id,
            name=self.name,
            state="healthy",
            message="System metrics are available.",
            checked_at=summary.collected_at,
        )

    def health(self) -> IntegrationHealth:
        try:
            return self.health_for(self.summary())
        except IntegrationError as error:
            return IntegrationHealth(
                id=self.integration_id,
                name=self.name,
                state="unavailable",
                message=str(error),
                checked_at=datetime.now(UTC),
            )

    def information(self) -> SystemInformation:
        identity = Identity(
            availability="available",
            source="configured",
            hostname=self._settings.system_hostname,
            os=self._settings.system_os_name,
            python_version=python_version(),
            api_version=version("ark-cloud-api"),
        )
        try:
            identity.kernel = release()
            identity.architecture = machine() or None
            identity.host_uptime_seconds = max(0, int(time() - psutil.boot_time()))
        except COLLECTION_ERRORS:
            identity.availability = "partial"

        compute = Compute(availability="available", source="kernel_view")
        try:
            compute.logical_cores = psutil.cpu_count() or None
            compute.percent = psutil.cpu_percent(interval=0.1)
        except COLLECTION_ERRORS:
            compute.availability = "partial"
        with suppress(*COLLECTION_ERRORS):
            compute.load_average = getloadavg()
        compute.model = _cpu_model()
        compute.gpus = _detected_gpus()
        try:
            frequency = psutil.cpu_freq()
            compute.frequency_mhz = frequency.current if frequency else None
        except COLLECTION_ERRORS:
            pass
        if compute.percent is None and compute.logical_cores is None:
            compute.availability = "unavailable"
        elif compute.model is None or compute.frequency_mhz is None or compute.load_average is None:
            compute.availability = "partial"
        if compute.gpus:
            compute.warning = "GPU detection does not imply API access or utilization measurements."

        memory = Memory(availability="available", source="kernel_view")
        try:
            ram = psutil.virtual_memory()
            memory.usage = _usage(ram.total, ram.total - ram.available, ram.available, ram.percent)
        except COLLECTION_ERRORS:
            memory.availability = "unavailable"
        try:
            swap = psutil.swap_memory()
            memory.swap = _usage(swap.total, swap.used, swap.free, swap.percent)
        except COLLECTION_ERRORS:
            memory.availability = "partial" if memory.usage else "unavailable"

        storage = Storage(
            availability="available",
            source="filesystem",
            path=self._settings.system_storage_path,
        )
        try:
            disk = psutil.disk_usage(storage.path)
            storage.usage = _usage(disk.total, disk.used, disk.free, disk.percent)
        except COLLECTION_ERRORS:
            storage.availability = "unavailable"
        try:
            # The path may not itself be a mount point; prefer the deepest matching mount.
            path = storage.path.rstrip("/") or "/"
            mounts = [
                part
                for part in psutil.disk_partitions(all=True)
                if path == part.mountpoint or path.startswith(part.mountpoint.rstrip("/") + "/")
            ]
            if mounts:
                storage.filesystem_type = (
                    max(mounts, key=lambda part: len(part.mountpoint)).fstype or None
                )
        except COLLECTION_ERRORS:
            pass
        if storage.usage and storage.filesystem_type is None:
            storage.availability = "partial"

        sensors = Sensors(availability="unavailable", source="runtime")
        try:
            readings = (
                psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
            )
            readings = readings or {}
            for group, entries in readings.items():
                if len(sensors.temperatures) >= 32:
                    break
                for index, entry in enumerate(entries, start=1):
                    if len(sensors.temperatures) >= 32:
                        break
                    if entry.current is not None and isfinite(entry.current):
                        raw_label = (entry.label or "").strip()
                        sensors.temperatures.append(
                            Temperature(
                                label=_temperature_label(group, raw_label, index),
                                source_name=(f"{group} / {raw_label}" if raw_label else group)[
                                    :120
                                ],
                                celsius=entry.current,
                            )
                        )
            if sensors.temperatures:
                sensors.availability = "available"
                sensors.warning = "Sensor placement may not be known."
            else:
                sensors.warning = "Temperature sensors are not available to the API runtime."
        except COLLECTION_ERRORS:
            sensors.warning = "Temperature sensors could not be read from the API runtime."

        return SystemInformation(
            collected_at=datetime.now(UTC),
            identity=identity,
            compute=compute,
            memory=memory,
            storage=storage,
            sensors=sensors,
        )
