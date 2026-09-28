"""FastAPI application factory.

This is the single backend. Both the Streamlit dashboard and the React
offline-first field PWA are HTTP clients of this app; neither opens its own
database session.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.config import get_settings
from api.router import api_router
from api.v1 import health

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Governance and compliance platform for coal mines (SIH26024, "
            "Team DATA_HELIX). All eight modules (M0-M7) are implemented "
            "and wired end to end: statutory rule registry, OCR document "
            "intelligence with Bhashini fallback, offline field evidence "
            "capture, a real MSHA-trained M3 accident-risk model, an "
            "unsupervised M5 sensor-anomaly detector over simulated "
            "telemetry, a CAPA/escalation loop with grievances and "
            "multi-stage approvals, a tamper-evident audit ledger, and "
            "role-based dashboards with a CDN-independent risk map. This "
            "is a hackathon prototype, not a certified or "
            "production-verified system - see the project README's "
            "\"Known limitations\" section before relying on any specific "
            "claim."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    # Unprefixed alias for the two probe endpoints only, so orchestrator
    # health checks have a stable path without duplicating the whole API.
    app.include_router(health.router)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """One failing dependency must not take the whole process down."""
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "path": request.url.path},
        )

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "app": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "health": f"{settings.api_v1_prefix}/health",
        }

    @app.on_event("startup")
    def _start_background_scheduler() -> None:
        """Real, live-interval automation for CAPA escalation and
        grievance SLA checks - see services/escalation_scheduler.py. Never
        started in the test environment: the test suite invokes the check
        functions directly and deterministically, and a background thread
        ticking during 200+ tests would be pure interference, not coverage."""
        if not settings.scheduler_enabled or settings.environment == "test":
            logger.info("Background scheduler disabled (scheduler_enabled=%s, environment=%s)",
                       settings.scheduler_enabled, settings.environment)
            return
        from app.database import get_sessionmaker
        from services.escalation_scheduler import start_scheduler
        app.state.scheduler = start_scheduler(get_sessionmaker())
        logger.info("Background scheduler started: interval=%ss", settings.scheduler_interval_seconds)

    @app.on_event("shutdown")
    def _stop_background_scheduler() -> None:
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    return app


app = create_app()
