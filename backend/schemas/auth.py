"""Authentication and user schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from models.enums import Role
from schemas.common import ORMModel


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    role: Role


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool
    mine_id: uuid.UUID | None = None
    subsidiary_id: uuid.UUID | None = None
    last_login_at: datetime | None = None


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=10, max_length=256)
    role: Role
    mine_id: uuid.UUID | None = None
    subsidiary_id: uuid.UUID | None = None
