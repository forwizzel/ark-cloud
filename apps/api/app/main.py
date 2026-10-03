from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.health import router as health_router
from app.api.local_storage import router as local_storage_router
from app.api.storage_admin import router as storage_admin_router
from app.api.system_host import router as system_host_router
from app.api.system_provision import router as system_provision_router
from app.api.tailscale_admin import router as tailscale_admin_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger = get_logger(__name__)
    settings = get_settings()
    from app.services.tailscale_control import initialize

    initialize(settings)
    logger.info(
        "service_started",
        extra={"environment": settings.environment, "service": settings.service_name},
    )
    yield
    logger.info("service_stopped", extra={"service": settings.service_name})


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title="Ark Cloud API",
        description="Private personal cloud control plane API",
        version="0.9.0",
        lifespan=lifespan,
        root_path="/api",
    )
    application.include_router(health_router)
    application.include_router(dashboard_router)
    application.include_router(auth_router)
    application.include_router(storage_admin_router)
    application.include_router(local_storage_router)
    application.include_router(tailscale_admin_router)
    application.include_router(system_host_router)
    application.include_router(system_provision_router)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        if request.url.path.startswith("/admin/tailscale"):
            return JSONResponse(
                status_code=422,
                content={"detail": "Invalid Tailscale request. Check the submitted fields."},
            )
        return await request_validation_exception_handler(request, error)

    return application


app = create_app()
