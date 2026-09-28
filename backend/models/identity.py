"""Users and authentication material."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, UuidPkMixin, enum_column
from models.enums import Role


class User(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    # bcrypt hash only. A plaintext password is never stored or logged.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = enum_column(Role, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Scope. A mine manager is scoped to one mine, a subsidiary head to a
    # subsidiary, a DGMS regulator to neither (national view).
    mine_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mines.id", ondelete="SET NULL"), index=True
    )
    subsidiary_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subsidiaries.id", ondelete="SET NULL"), index=True
    )

    mine = relationship("Mine", back_populates="users", foreign_keys=[mine_id])
    subsidiary = relationship("Subsidiary", foreign_keys=[subsidiary_id])
