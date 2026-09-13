from datetime import UTC, datetime
from platform import release
from time import time

import psutil

from app.core.config import Settings
from app.integrations.base import Integration, IntegrationError
from app.schemas.integrations import IntegrationHealth, ResourceUsage, SystemSummary


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
