"""Response models for the health endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DatabaseHealth(BaseModel):
    backend: str = Field(description="postgresql or sqlite")
    reachable: bool
    is_development_fallback: bool = Field(
        description="True when running on the SQLite development fallback rather than PostgreSQL."
    )
    detail: str


class HealthResponse(BaseModel):
    status: str = Field(description="ok or degraded")
    app: str
    version: str
    environment: str
    phase: str
    server_time_utc: datetime
    database: DatabaseHealth


class ReadinessResponse(BaseModel):
    ready: bool
    checks: dict[str, str]
