from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import Settings, get_settings
from app.core.database import DatabaseState, get_database_state
from app.dependencies import get_system_integration, get_tailscale_integration
from app.integrations.base import IntegrationError
from app.integrations.system import SystemIntegration
from app.integrations.tailscale import TailscaleIntegration
from app.schemas.health import HealthResponse
from app.schemas.integrations import (
    DashboardResponse,
    IntegrationHealth,
    SystemSummary,
    TailscaleSummary,
)

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    database: Annotated[DatabaseState, Depends(get_database_state)],
    settings: Annotated[Settings, Depends(get_settings)],
    system_integration: Annotated[SystemIntegration, Depends(get_system_integration)],
    tailscale_integration: Annotated[TailscaleIntegration, Depends(get_tailscale_integration)],
) -> DashboardResponse:
    system_summary: SystemSummary | None = None
    try:
        system_summary = system_integration.summary()
        system_health = system_integration.health_for(system_summary)
    except IntegrationError as error:
        system_health = IntegrationHealth(
            id=system_integration.integration_id,
            name=system_integration.name,
            state="unavailable",
            message=str(error),
            checked_at=datetime.now(UTC),
        )

    tailscale_summary = tailscale_integration.summary()
    return DashboardResponse(
        platform=_platform_health(settings, database),
        system=system_summary,
        tailscale=tailscale_summary,
        integrations=[system_health, tailscale_integration.health_for(tailscale_summary)],
        generated_at=datetime.now(UTC),
    )


@router.get("/system", response_model=SystemSummary, tags=["system"])
def system_summary(
    integration: Annotated[SystemIntegration, Depends(get_system_integration)],
) -> SystemSummary:
    try:
        return integration.summary()
    except IntegrationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error


@router.get("/integrations", response_model=list[IntegrationHealth], tags=["integrations"])
def integration_health(
    system_integration: Annotated[SystemIntegration, Depends(get_system_integration)],
    tailscale_integration: Annotated[TailscaleIntegration, Depends(get_tailscale_integration)],
) -> list[IntegrationHealth]:
    return [system_integration.health(), tailscale_integration.health()]


@router.get("/tailscale/devices", response_model=TailscaleSummary, tags=["tailscale"])
def tailscale_devices(
    integration: Annotated[TailscaleIntegration, Depends(get_tailscale_integration)],
) -> TailscaleSummary:
    return integration.summary()


def _platform_health(settings: Settings, database: DatabaseState) -> HealthResponse:
    return HealthResponse(
        status="healthy" if database == "connected" else "unhealthy",
        service=settings.service_name,
        database=database,
    )
