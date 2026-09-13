from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.integrations.system import SystemIntegration
from app.integrations.tailscale import TailscaleIntegration


def get_system_integration(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SystemIntegration:
    return SystemIntegration(settings)


def get_tailscale_integration(
    settings: Annotated[Settings, Depends(get_settings)],
) -> TailscaleIntegration:
    return TailscaleIntegration(settings)
