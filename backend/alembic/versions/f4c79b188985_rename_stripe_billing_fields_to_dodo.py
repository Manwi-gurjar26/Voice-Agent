"""rename stripe billing fields to dodo

Revision ID: f4c79b188985
Revises: 5ff2ab439513
Create Date: 2026-07-31 12:00:00.000000

Stripe does not onboard new India-registered accounts, so this platform's
billing provider was swapped to Dodo Payments (a merchant-of-record gateway
available to India-based merchants) before ever going live on Stripe. A
plain rename, not a drop+add — no tenant had checked out yet, but the
pattern (op.alter_column, not autogenerate's drop-then-add) is what you'd
want here regardless, per the README's autogenerate rename warning.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = 'f4c79b188985'
down_revision: str | None = '5ff2ab439513'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column('tenants', 'stripe_customer_id', new_column_name='dodo_customer_id')
    op.alter_column('tenants', 'stripe_subscription_id', new_column_name='dodo_subscription_id')
    op.drop_constraint('uq_tenants_stripe_customer_id', 'tenants', type_='unique')
    op.drop_constraint('uq_tenants_stripe_subscription_id', 'tenants', type_='unique')
    op.create_unique_constraint('uq_tenants_dodo_customer_id', 'tenants', ['dodo_customer_id'])
    op.create_unique_constraint('uq_tenants_dodo_subscription_id', 'tenants', ['dodo_subscription_id'])


def downgrade() -> None:
    op.drop_constraint('uq_tenants_dodo_subscription_id', 'tenants', type_='unique')
    op.drop_constraint('uq_tenants_dodo_customer_id', 'tenants', type_='unique')
    op.alter_column('tenants', 'dodo_subscription_id', new_column_name='stripe_subscription_id')
    op.alter_column('tenants', 'dodo_customer_id', new_column_name='stripe_customer_id')
    op.create_unique_constraint('uq_tenants_stripe_customer_id', 'tenants', ['stripe_customer_id'])
    op.create_unique_constraint('uq_tenants_stripe_subscription_id', 'tenants', ['stripe_subscription_id'])
