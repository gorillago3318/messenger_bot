from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision = '123123abc'
down_revision = '1234abcdcc12'
branch_labels = None
depends_on = None


def upgrade():
    # Create Users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('messenger_id', sa.String(length=50), nullable=False, unique=True),
        sa.Column('name', sa.String(length=100)),
        sa.Column('phone_number', sa.String(length=15)),
        sa.Column('language', sa.String(length=10)),
        sa.Column('state', sa.String(length=50)),
        sa.Column('outstanding_balance', sa.Float()),
        sa.Column('current_interest_rate', sa.Float()),
        sa.Column('remaining_tenure', sa.Float()),
        sa.Column('original_amount', sa.Float()),
        sa.Column('original_tenure', sa.Float()),
        sa.Column('current_monthly_payment', sa.Float()),
        sa.Column('years_paid', sa.Float()),
        sa.Column('monthly_savings', sa.Float()),
        sa.Column('yearly_savings', sa.Float()),
        sa.Column('total_savings', sa.Float()),
        sa.Column('tenure', sa.Float()),
        sa.Column('current_rate', sa.Float()),
        sa.Column('new_rate', sa.Float()),
        sa.Column('temp_cashout_amount', sa.Float()),
        sa.PrimaryKeyConstraint('id')
    )

    # Create Leads table
    op.create_table(
        'leads',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('sender_id', sa.String(length=20), nullable=False),
        sa.Column('phone_number', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('original_loan_amount', sa.Float(), nullable=False),
        sa.Column('original_loan_tenure', sa.Integer(), nullable=False),
        sa.Column('current_repayment', sa.Float(), nullable=False),
        sa.Column('new_repayment', sa.Float(), nullable=False),
        sa.Column('monthly_savings', sa.Float(), nullable=False),
        sa.Column('yearly_savings', sa.Float(), nullable=False),
        sa.Column('total_savings', sa.Float(), nullable=False),
        sa.Column('years_saved', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # Create BankRates table
    op.create_table(
        'bank_rates',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('bank_name', sa.String(length=100), nullable=False),
        sa.Column('min_amount', sa.Float(), nullable=False),
        sa.Column('max_amount', sa.Float(), nullable=False),
        sa.Column('interest_rate', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

def downgrade():
    op.drop_table('bank_rates')
    op.drop_table('leads')
    op.drop_table('users')
