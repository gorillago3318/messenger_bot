from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = 'abcd1234cc12'
down_revision = 'b36d0880cca4'
branch_labels = None
depends_on = None

def upgrade():
    # Manually add schema changes (creating tables, adding columns, etc.)
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('phone_number', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Add other tables in a similar way
    # You can also use 'op.create_column', 'op.add_column', etc.
    op.create_table(
        'chatflow_temp',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('messenger_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
def downgrade():
    op.drop_table('users')
    op.drop_table('chatflow_temp')
