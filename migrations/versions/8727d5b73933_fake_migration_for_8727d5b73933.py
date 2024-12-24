"""Fake migration for 8727d5b73933

Revision ID: 8727d5b73933
Revises: a166d0439762
Create Date: 2024-12-25 00:24:49.839748

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8727d5b73933'
down_revision = 'a166d0439762'
branch_labels = None
depends_on = None


def upgrade():
    pass  # No schema changes, just a placeholder

def downgrade():
    pass  # No schema changes, just a placeholder