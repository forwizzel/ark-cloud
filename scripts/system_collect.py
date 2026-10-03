"""Bounded Linux host collection; never imported into the API container."""

import json
import math
import os
import platform
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

ERRORS = (OSError, ValueError, RuntimeError, psutil.Error)
UTC = timezone.utc


def text(path, limit=4096):
    try:
        with open(path, encoding="utf-8", errors="replace") as stream:
            return stream.read(limit).strip()
    except OSError:
        return ""


def finite(value):
    return value if value is not None and math.isfinite(value) else None


def usage(total, used, available, percent):
    return {
        "total_bytes": max(0, total),
        "used_bytes": max(0, used),
        "available_bytes": max(0, available),
        "percent": min(100, max(0, percent)),
    }


def sensor_group(driver, label):
    if driver in {"coretemp", "k10temp", "cpu_thermal"}:
        return "cpu"
    if driver in {"amdgpu", "nouveau", "nvidia"}:
        return "gpu"
    if driver == "jc42":
        return "memory"
    if driver in {"nvme", "drivetemp"}:
        return "storage"
    if driver == "asusec" or any(
        word in label.lower() for word in ("motherboard", "vrm", "chipset")
    ):
        return "motherboard"
    return "other"


class Collector:
    def __init__(self):
        self.previous_io = None
        self.previous_time = None
        self.warm = False
        self.services = []
        self.service_time = 0

    def collect(self, policy):
        warnings = []
        was_warm = self.warm
        boot = psutil.boot_time()
        os_name = platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
        cpuinfo = text("/proc/cpuinfo", 262144)
        model = next(
            (
                line.partition(":")[2].strip()
                for line in cpuinfo.splitlines()
                if line.startswith("model name")
            ),
            None,
        )
        sockets = {
            line.partition(":")[2].strip()
            for line in cpuinfo.splitlines()
            if line.startswith("physical id")
        }
        compute = {
            "model": model[:256] if model else None,
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(),
            "sockets": len(sockets) or None,
            "percent": None,
            "per_core": [],
            "frequency_mhz": None,
            "load_average": os.getloadavg(),
            "gpus": [],
        }
        try:
            percent = psutil.cpu_percent()
            per_core = psutil.cpu_percent(percpu=True)[:1024]
            if self.warm:
                compute.update(percent=percent, per_core=per_core)
            freq = psutil.cpu_freq()
            compute["frequency_mhz"] = finite(freq.current) if freq else None
        except ERRORS:
            warnings.append("Some compute measurements are unavailable.")
        self.warm = True
        try:
            for card in sorted(Path("/sys/class/drm").glob("card[0-9]*"))[:64]:
                if not card.name.removeprefix("card").isdigit():
                    continue
                vendor = text(card / "device/vendor", 16)
                device = text(card / "device/device", 16)
                if vendor:
                    name = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel"}.get(
                        vendor, vendor
                    )
                    compute["gpus"].append(f"{name} GPU (PCI {vendor}:{device})")
                if len(compute["gpus"]) == 16:
                    break
        except ERRORS:
            pass
        memory = {
            "usage": None,
            "swap": None,
            "cached_bytes": None,
            "buffers_bytes": None,
            "swap_in_bytes": None,
            "swap_out_bytes": None,
        }
        try:
            ram = psutil.virtual_memory()
            memory.update(
                usage=usage(ram.total, ram.total - ram.available, ram.available, ram.percent),
                cached_bytes=getattr(ram, "cached", None),
                buffers_bytes=getattr(ram, "buffers", None),
            )
        except ERRORS:
            warnings.append("Host memory could not be read.")
        try:
            swap = psutil.swap_memory()
            memory.update(
                swap=usage(swap.total, swap.used, swap.free, swap.percent),
                swap_in_bytes=swap.sin,
                swap_out_bytes=swap.sout,
            )
        except ERRORS:
            warnings.append("Swap measurements are unavailable.")
        temperatures = []
        try:
            for driver, entries in psutil.sensors_temperatures().items():
                for index, entry in enumerate(entries):
                    if len(temperatures) >= 128:
                        break
                    if finite(entry.current) is None:
                        continue
                    label = entry.label or f"{driver} sensor {index + 1}"
                    temperatures.append(
                        {
                            "id": f"{driver}:{index}:{label}"[:256],
                            "group": sensor_group(driver, label),
                            "label": label[:256],
                            "source_name": f"{driver} / {label}"[:256],
                            "celsius": entry.current,
                            "high": finite(entry.high),
                            "critical": finite(entry.critical),
                        }
                    )
        except ERRORS:
            warnings.append("Temperature sensors could not be read.")
        mounts, omitted, seen = [], [], set()
        try:
            for part in psutil.disk_partitions(all=True)[:512]:
                try:
                    dev = os.stat(part.mountpoint).st_dev
                    if not part.device.startswith("/dev/") or dev in seen:
                        if len(omitted) < 128:
                            omitted.append(part.mountpoint[:256])
                        continue
                    seen.add(dev)
                    disk = psutil.disk_usage(part.mountpoint)
                    value = usage(disk.total, disk.used, disk.free, disk.percent)
                except ERRORS:
                    value = None
                mounts.append(
                    {
                        "id": part.mountpoint[:256],
                        "path": part.mountpoint[:2048],
                        "device": part.device[:256],
                        "filesystem": part.fstype[:256],
                        "options": part.opts[:256],
                        "usage": value,
                    }
                )
                if len(mounts) >= 128:
                    break
        except ERRORS:
            warnings.append("Host filesystems could not be enumerated.")
        disk_io = []
        try:
            current = psutil.disk_io_counters(perdisk=True) or {}
            stamp = time.monotonic()
            for name, counters in list(current.items())[:128]:
                previous = (self.previous_io or {}).get(name)
                interval = stamp - self.previous_time if self.previous_time else 0
                disk_io.append(
                    {
                        "device": name[:256],
                        "read_bytes": counters.read_bytes,
                        "write_bytes": counters.write_bytes,
                        "read_bytes_per_second": max(0, counters.read_bytes - previous.read_bytes)
                        / interval
                        if previous and interval
                        else None,
                        "write_bytes_per_second": max(
                            0, counters.write_bytes - previous.write_bytes
                        )
                        / interval
                        if previous and interval
                        else None,
                    }
                )
            self.previous_io, self.previous_time = current, stamp
        except ERRORS:
            warnings.append("Device I/O counters are unavailable.")
        processes = []
        if policy["processes"]:
            for process in psutil.process_iter(
                ["pid", "name", "username", "create_time", "memory_info", "status"]
            ):
                try:
                    info = process.info
                    if info["create_time"] is None or info["memory_info"] is None:
                        continue
                    cpu_percent = process.cpu_percent()
                    processes.append(
                        {
                            "pid": process.pid,
                            "started_at": info["create_time"],
                            "owner": (info["username"] or "Unknown")[:256],
                            "name": (info["name"] or "Unknown")[:256],
                            "percent": min(100, cpu_percent / (psutil.cpu_count() or 1))
                            if was_warm
                            else None,
                            "memory_bytes": info["memory_info"].rss,
                            "state": info["status"][:256],
                        }
                    )
                except ERRORS:
                    continue
                if len(processes) >= 2048:
                    warnings.append("Process list is limited to 2,048 entries.")
                    break
        if time.monotonic() - self.service_time > 15:
            self.services = []
            budget_start = time.monotonic()
            for service in policy["services"]:
                command = [
                    "systemctl",
                    *(["--user"] if service["scope"] == "user" else []),
                    "show",
                    "--property=ActiveState",
                    "--value",
                    service["unit"],
                ]
                try:
                    if time.monotonic() - budget_start > 3:
                        raise RuntimeError("Service sampling budget exceeded")
                    result = subprocess.run(command, capture_output=True, text=True, timeout=2)
                    state = result.stdout.strip()[:256] if not result.returncode else "unavailable"
                except ERRORS + (subprocess.SubprocessError,):
                    state = "unavailable"
                self.services.append({**service, "state": state or "unknown"})
            self.service_time = time.monotonic()
        return {
            "version": 1,
            "scope": "host",
            "boot_id": text("/proc/sys/kernel/random/boot_id", 64),
            "collected_at": datetime.now(UTC).isoformat(),
            "identity": {
                "hostname": socket.gethostname()[:256],
                "os": os_name[:256],
                "kernel": platform.release()[:256],
                "architecture": platform.machine()[:256],
                "boot_time": datetime.fromtimestamp(boot, UTC).isoformat(),
                "uptime_seconds": max(0, int(time.time() - boot)),
            },
            "compute": compute,
            "memory": memory,
            "temperatures": temperatures,
            "mounts": mounts,
            "omitted_mounts": omitted,
            "disk_io": disk_io,
            "processes": processes,
            "services": self.services,
            "warnings": warnings,
            "availability": {
                "compute": "available" if compute["percent"] is not None and model else "partial",
                "memory": "available"
                if memory["usage"] and memory["swap"]
                else "partial"
                if memory["usage"]
                else "unavailable",
                "temperatures": "available" if temperatures else "unavailable",
                "storage": "available"
                if mounts and all(m["usage"] for m in mounts)
                else "partial"
                if mounts
                else "unavailable",
            },
        }


if __name__ == "__main__":
    policy = json.loads(sys.stdin.readline())
    collector = Collector()
    while True:
        print(json.dumps(collector.collect(policy)), flush=True)
        time.sleep(5)
