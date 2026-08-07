"""allow crawl source_type on documents

Revision ID: 598ca81775f1
Revises: f4c79b188985
Create Date: 2026-08-07 18:11:57.410109
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '598ca81775f1'
down_revision: str | None = 'f4c79b188985'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Autogenerate doesn't detect CHECK constraint body changes — written by
    # hand. Postgres has no ALTER CHECK; drop and recreate under the same
    # name, matching Document's own source_type_valid constraint name.
    op.drop_constraint("source_type_valid", "documents", type_="check")
    op.create_check_constraint(
        "source_type_valid", "documents", "source_type IN ('text', 'file', 'url', 'crawl')"
    )


def downgrade() -> None:
    op.drop_constraint("source_type_valid", "documents", type_="check")
    op.create_check_constraint(
        "source_type_valid", "documents", "source_type IN ('text', 'file', 'url')"
    )
