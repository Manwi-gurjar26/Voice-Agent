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
    """Maps to Claude's `output_config.effort`.

    This replaces the `temperature` knob you'd expect from older APIs — current
    Claude models reject `temperature`, `top_p`, and `top_k` with a 400.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"
