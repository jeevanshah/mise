"""epic11 hardening - purchase order line source tracking

Revision ID: 0011_epic11
Revises: 0010_epic10
Create Date: 2026-09-17 22:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0011_epic11'
down_revision = '0010_epic10'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Metrics wiring checklist (locked spec): "PurchaseOrder 'sent' events
    # logged with source (manual vs. from Capture)" — this is a genuine gap
    # Epic 11's own audit-coverage pass found: nothing on PurchaseOrderLine
    # recorded who/what created it. NOT NULL with a server_default so this
    # can't fail on a deployed DB with existing rows (same pattern as Epic
    # 7's added_after_close columns).
    op.add_column(
        'purchase_order_lines',
        sa.Column('source', sa.String(length=20), nullable=False, server_default='manual'),
    )


def downgrade() -> None:
    op.drop_column('purchase_order_lines', 'source')
