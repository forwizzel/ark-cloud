"""Normalized external and system integration adapters."""

from app.integrations.base import Integration, IntegrationError
from app.integrations.system import SystemIntegration
from app.integrations.tailscale import TailscaleIntegration

__all__ = [
    "Integration",
    "IntegrationError",
    "SystemIntegration",
    "TailscaleIntegration",
]
