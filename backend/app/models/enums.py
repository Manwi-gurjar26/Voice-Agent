"""Enum values shared across models.

Stored as VARCHAR + CHECK rather than native PG enums: adding a value to a
native enum requires ALTER TYPE, which is awkward inside a transactional
migration and impossible to roll back cleanly.
"""

from __future__ import annotations

from enum import StrEnum


class PlanTier(StrEnum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class UserRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class AgentStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"


class EffortLevel(StrEnum):
    """Maps to Gemini's `thinking_config.thinking_budget` (a token count) —
    see `_THINKING_BUDGET_BY_EFFORT` in app/services/chat.py.

    Originally modeled on Claude's `output_config.effort`, which replaced the
    `temperature` knob for that provider. Kept as this same 5-level scale
    across the Anthropic -> Gemini swap so no migration was needed — only the
    mapping in the LLM call itself changed.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"
