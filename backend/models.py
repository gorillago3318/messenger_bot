from datetime import datetime
from backend.extensions import db
import pytz
from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, JSON

# Malaysia timezone
MYT = pytz.timezone('Asia/Kuala_Lumpur')

# ----------------------------
# Users Table (Simplified)
# ----------------------------
# Inside backend/models.py

from backend.extensions import db

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    messenger_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100))
    phone_number = db.Column(db.String(15))
    language = db.Column(db.String(10))
    state = db.Column(db.String(50))

    # Path A fields
    outstanding_balance = db.Column(db.Float)
    current_interest_rate = db.Column(db.Float)
    remaining_tenure = db.Column(db.Float)

    # Path B fields
    original_amount = db.Column(db.Float)
    original_tenure = db.Column(db.Float)
    current_monthly_payment = db.Column(db.Float)
    years_paid = db.Column(db.Float)

    monthly_savings = db.Column(db.Float)
    yearly_savings = db.Column(db.Float)
    total_savings = db.Column(db.Float)
    tenure = db.Column(db.Float)
    current_rate = db.Column(db.Float)
    new_rate = db.Column(db.Float)

    # Cash-Out fields
    temp_cashout_amount = db.Column(db.Float)  # Added field

    # New field for tracking last interaction
    last_interaction = db.Column(db.DateTime, default=datetime.utcnow)  # Add this line

    def __repr__(self):
        return f"<User {self.name}>"

    # Add other necessary fields here

# ----------------------------
# Leads Table (Simplified)
# ----------------------------
class Lead(db.Model):
    __tablename__ = 'leads'

    id = db.Column(Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(Integer, ForeignKey('users.id'), index=True, nullable=False)
    sender_id = db.Column(String(20), nullable=False)  # Messenger ID
    phone_number = db.Column(String(20), nullable=False)  # Required phone number
    name = db.Column(String(50), nullable=False)  # Required name

    # Loan Details
    original_loan_amount = db.Column(Float, nullable=False)
    original_loan_tenure = db.Column(Integer, nullable=False)
    current_repayment = db.Column(Float, nullable=False)

    # Savings and Calculation Fields
    new_repayment = db.Column(Float, nullable=False)
    monthly_savings = db.Column(Float, nullable=False)
    yearly_savings = db.Column(Float, nullable=False)
    total_savings = db.Column(Float, nullable=False)
    years_saved = db.Column(Integer, nullable=False)

    created_at = db.Column(DateTime, default=lambda: datetime.now(MYT))
    updated_at = db.Column(DateTime, default=lambda: datetime.now(MYT), onupdate=lambda: datetime.now(MYT))


# ----------------------------
# BankRate Table (Simplified)
# ----------------------------
class BankRate(db.Model):
    __tablename__ = 'bank_rates'

    id = db.Column(Integer, primary_key=True, autoincrement=True)
    bank_name = db.Column(String(100), nullable=False)
    min_amount = db.Column(Float, nullable=False)
    max_amount = db.Column(Float, nullable=False)
    interest_rate = db.Column(Float, nullable=False)
    created_at = db.Column(DateTime, default=lambda: datetime.now(MYT))
    updated_at = db.Column(DateTime, default=lambda: datetime.now(MYT), onupdate=lambda: datetime.now(MYT))
