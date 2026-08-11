"""point existing agents at the groq chat model

Revision ID: 0b0e9bc0e7c4
Revises: aced294f4a1a
Create Date: 2026-08-11 12:37:01.366447
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0b0e9bc0e7c4'
down_revision: str | None = 'aced294f4a1a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Typed chat moved from Gemini to Groq, and agents.model names the model
    that request is actually sent to. Rows still holding a Gemini model name
    would be rejected by Groq as unknown, so every existing agent is pointed
    at the new default. Agents already on a non-Gemini model are left alone.
    """
    op.execute(
        sa.text(
            "UPDATE agents SET model = :model WHERE model LIKE 'gemini%'"
        ).bindparams(model="llama-3.3-70b-versatile")
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE agents SET model = :model WHERE model LIKE 'llama%'"
        ).bindparams(model="gemini-flash-latest")
    )
