from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.config import settings
from app.models.enums import PlanTier, UserRole


class _Password(BaseModel):
    password: str = Field(min_length=1, max_length=256)

    @field_validator("password")
    @classmethod
    def _policy(cls, value: str) -> str:
        if len(value) < settings.min_password_length:
            raise ValueError(
                f"password must be at least {settings.min_password_length} characters"
            )
        # Length is the dominant factor in resistance to guessing; a single
        # character-class rule catches the worst all-lowercase choices without
        # pushing users toward "Password1!" patterns.
        if value.isalpha() or value.isdigit():
            raise ValueError("password must mix letters with numbers or symbols")
        return value


class SignupRequest(_Password):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=200)
    company_name: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _normalise(cls, value: str) -> str:
        # The users table has a CHECK (email = lower(email)); normalising here
        # keeps that constraint from ever being the thing that reports the error.
        return value.strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return value.strip().lower()


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return value.strip().lower()


class ResetPasswordRequest(_Password):
    """`password` here is the field name (not `new_password`): reuses
    _Password's policy validator as-is rather than duplicating it under a
    different field name."""

    token: str = Field(min_length=1, max_length=512)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    plan: PlanTier
    monthly_message_quota: int
    # Usage-this-period, so the dashboard's billing page needs no second
    # endpoint. Raw Dodo identifiers are deliberately not exposed here —
    # the dashboard only needs plan/usage, not Dodo's internal ids.
    messages_used_in_period: int
    period_started_at: datetime


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class MeResponse(BaseModel):
    user: UserRead
    tenant: TenantRead
