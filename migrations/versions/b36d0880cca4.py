"""Fake migration to bypass revision error"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = 'b36d0880cca4'  # Fake revision ID
down_revision = None  # No previous revision
branch_labels = None
depends_on = None

def upgrade():
    # No operation, just to bypass the error
    pass

def downgrade():
    # No operation, just to bypass the error
    pass
