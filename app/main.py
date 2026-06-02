"""FastAPI application entry point.

Run with:

    uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import api_router
from app.core.config import settings
from app.core.database import init_metadata_tables
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    configure_logging()
    log = get_logger("app.main")
    log.info("Starting %s (env=%s)", settings.app_name, settings.app_env)
    try:
        init_metadata_tables()
    except Exception as exc:  # noqa: BLE001 — DB might be unavailable during dev
        log.warning("Metadata table init skipped: %s", exc)
    yield
    log.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Intelligent file → MySQL → analytics pipeline.\n\n"
            "Bronze / Silver / Gold layers in MySQL with a "
            "human-in-the-loop relationship-approval step."
        ),
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "app": settings.app_name}

    return app


app = create_app()
