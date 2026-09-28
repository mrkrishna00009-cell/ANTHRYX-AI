"""Aggregates all versioned routers.

Phase 2 registers the M0-M7 API foundations. Where a module's
intelligence is not built, its endpoint returns an explicit
NotImplementedNotice with HTTP 501 rather than a placeholder result.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.v1 import (
    approvals, audit, auth, capa, contractors, documents, field_evidence, grievances,
    health, mines, risk, sensors, statutory,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(mines.router)
api_router.include_router(statutory.router)     # M0
api_router.include_router(documents.router)     # M1
api_router.include_router(field_evidence.router)  # M2
api_router.include_router(risk.router)          # M3
api_router.include_router(capa.router)          # M4
api_router.include_router(sensors.router)       # M5
api_router.include_router(audit.router)         # M6
api_router.include_router(grievances.router)
api_router.include_router(approvals.router)
api_router.include_router(contractors.router)
