"""Declarative base and shared column mixins.

Naming conventions are set explicitly so Alembic can autogenerate stable
constraint names later, and so the schema stays portable between the
PostgreSQL primary and the SQLite development fallback.
"""

from __future__ import annotations

from datetime import datetime, timezone

import uuid

from sqlalchemy import DateTime, Enum as SAEnum, MetaData, func
from sqlalchemy import Uuid as SAUuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    """Server-authoritative timestamps.

    Client-supplied times are never used as the authoritative record; see
    the M2 field-evidence design, where the client clock is stored only for
    comparison against the server clock.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UuidPkMixin:
    """Stable, non-guessable primary key.

    ``sqlalchemy.Uuid`` maps to native UUID on PostgreSQL and CHAR(32) on
    SQLite, so the identifier is stable across both backends.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(), primary_key=True, default=uuid.uuid4
    )


def enum_column(enum_cls, **kwargs):
    """Portable enum column: VARCHAR + CHECK rather than a PG ENUM type."""
    return mapped_column(
        SAEnum(
            enum_cls,
            native_enum=False,
            length=48,
            validate_strings=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        **kwargs,
    )
