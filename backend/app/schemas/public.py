from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentPublicConfig(BaseModel):
    """What the widget needs to render itself, before any session exists.

    This is a strict allowlist, not "AgentRead minus a few fields" — if it were
    derived from AgentRead, a future field added there (e.g. an internal note,
    a webhook URL) would leak to every visitor's browser by default instead of
    by deliberate choice. Deliberately excluded: system_prompt, model, effort,
    allowed_origins, rate_limit_per_minute, tenant_id — none of that belongs
    where page source and the network tab can read it.
    """

    model_config = ConfigDict(from_attributes=True)

    name: str
    greeting: str
    voice_enabled: bool
    theme: dict[str, Any]


class WidgetSessionResponse(BaseModel):
    session_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Widget session lifetime in seconds.")


class WidgetSessionInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    expires_at: datetime
