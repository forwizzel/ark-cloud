from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core.config import Settings, get_settings
from app.core.database import DatabaseState, get_database_state
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Check API and database health",
)
def health(
    response: Response,
    database: Annotated[DatabaseState, Depends(get_database_state)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    is_healthy = database == "connected"
    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="healthy" if is_healthy else "unhealthy",
        service=settings.service_name,
        database=database,
    )
