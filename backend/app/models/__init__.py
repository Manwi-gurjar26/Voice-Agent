"""Model package.

Importing every model here is what makes `Base.metadata` complete — Alembic's
autogenerate only sees tables whose modules have been imported.
"""

from app.models.agent import Agent
from app.models.chunk import Chunk
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.enums import AgentStatus, EffortLevel, PlanTier, UserRole
from app.models.message import Message
from app.models.refresh_token import RefreshToken
from app.models.tenant import Tenant
from app.models.user import User
from app.models.widget_session import WidgetSession

__all__ = [
    "Agent",
    "AgentStatus",
    "Chunk",
    "Conversation",
    "Document",
    "EffortLevel",
    "Message",
    "PlanTier",
    "RefreshToken",
    "Tenant",
    "User",
    "UserRole",
    "WidgetSession",
]
