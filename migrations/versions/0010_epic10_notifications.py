"""epic10 operational email notifications

Revision ID: 0010_epic10
Revises: 0009_epic9
Create Date: 2026-09-17 22:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0010_epic10'
down_revision = '0009_epic9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The one schema change this epic needs: a delivery address for a Staff
    # member with no login at all (user_id is None), so a signed shift link
    # can actually be emailed to them — see app/models/staff.py's own
    # docstring. Everything else (dedup, the trigger checks) is derived
    # against existing tables/AuditEvent, no new tables needed.
    op.add_column('staff', sa.Column('contact_email', sa.String(length=320), nullable=True))


def downgrade() -> None:
    op.drop_column('staff', 'contact_email')
