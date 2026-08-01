from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.core.config import settings
from app.models.agent import Agent
from app.models.enums import AgentStatus, EffortLevel

MAX_ORIGINS = 50

# Piper voice names (see app/services/voice.py) — a small, verified subset
# of real voices from https://github.com/rhasspy/piper/blob/master/VOICES.md,
# each confirmed downloadable before being added here. Validated here, at
# the boundary, so a bad voice_id surfaces as a normal 422 on agent
# create/update instead of a failed download the next time someone speaks
# to the widget.
ALLOWED_VOICE_IDS = {
    "en_US-lessac-medium",
    "en_US-amy-medium",
    "en_US-ryan-medium",
    "en_GB-alan-medium",
}


def _validate_voice_id(value: str | None) -> str | None:
    if value is not None and value not in ALLOWED_VOICE_IDS:
        raise ValueError(f"voice_id must be one of {sorted(ALLOWED_VOICE_IDS)}: {value!r}")
    return value


def _normalise_origins(value: list[str]) -> list[str]:
    """Normalise, validate, and de-duplicate an origin allowlist.

    Stored entries must be bare `scheme://host[:port]`, matching what browsers
    put in the Origin header — otherwise the runtime check silently never
    matches and every widget request is rejected.
    """
    if len(value) > MAX_ORIGINS:
        raise ValueError(f"at most {MAX_ORIGINS} origins are allowed")

    seen: dict[str, None] = {}
    for raw in value:
        try:
            origin = Agent.normalize_origin(raw)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        scheme = origin.split("://", 1)[0]
        if scheme not in ("http", "https"):
            raise ValueError(f"origin scheme must be http or https: {raw!r}")
        if scheme == "http" and not origin.startswith(("http://localhost", "http://127.0.0.1")):
            raise ValueError(
                f"plain http origins are only allowed for localhost: {raw!r}"
            )
        seen[origin] = None
    return list(seen)


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    system_prompt: str | None = Field(default=None, max_length=100_000)
    greeting: str | None = Field(default=None, max_length=2_000)
    model: str | None = Field(default=None, max_length=60)
    effort: EffortLevel = EffortLevel.MEDIUM
    max_output_tokens: int = Field(default=2048, ge=256, le=128_000)
    voice_enabled: bool = False
    voice_id: str | None = Field(default=None, max_length=80)
    theme: dict[str, Any] | None = None
    allowed_origins: list[str] = Field(default_factory=list)

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, value: list[str]) -> list[str]:
        return _normalise_origins(value)

    @field_validator("voice_id")
    @classmethod
    def _voice_id(cls, value: str | None) -> str | None:
        return _validate_voice_id(value)


class AgentUpdate(BaseModel):
    """Every field optional — this is a PATCH body.

    `tenant_id`, `public_key`, and `id` are deliberately absent: they are not
    client-settable, and omitting them from the schema means a hostile payload
    cannot reassign an agent to another tenant.
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: AgentStatus | None = None
    system_prompt: str | None = Field(default=None, max_length=100_000)
    greeting: str | None = Field(default=None, max_length=2_000)
    model: str | None = Field(default=None, max_length=60)
    effort: EffortLevel | None = None
    max_output_tokens: int | None = Field(default=None, ge=256, le=128_000)
    voice_enabled: bool | None = None
    voice_id: str | None = Field(default=None, max_length=80)
    theme: dict[str, Any] | None = None
    allowed_origins: list[str] | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=1_000)

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _normalise_origins(value)

    @field_validator("voice_id")
    @classmethod
    def _voice_id(cls, value: str | None) -> str | None:
        return _validate_voice_id(value)


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    public_key: str
    status: AgentStatus
    system_prompt: str
    greeting: str
    model: str
    effort: EffortLevel
    max_output_tokens: int
    voice_enabled: bool
    voice_id: str | None
    theme: dict[str, Any]
    allowed_origins: list[str]
    rate_limit_per_minute: int
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def embed_snippet(self) -> str:
        """Copy-paste snippet for the customer's site."""
        return (
            f'<script src="{settings.widget_cdn_url}" '
            f'data-agent-key="{self.public_key}" async></script>'
        )


class AgentListResponse(BaseModel):
    items: list[AgentRead]
    total: int
