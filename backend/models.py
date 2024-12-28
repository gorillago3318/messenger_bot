from datetime import datetime
from backend.extensions import db
import pytz
from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, Text

# Malaysia timezone
MYT = pytz.timezone('Asia/Kuala_Lumpur')

# ----------------------------
# ChatflowTemp Model
# ----------------------------
class ChatflowTemp(db.Model):
    __tablename__ = 'chatflow_temp'

    id = Column(Integer, primary_key=True, autoincrement=True)
    sender_id = Column(String(20), nullable=True)  # Allow null temporarily
    messenger_id = Column(String(50), nullable=True)  # Messenger ID for Messenger Bot
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)  # ForeignKey reference to users
    current_step = Column(String(50), nullable=True)
    language_code = Column(String(10), nullable=True)
    name = Column(String(100), nullable=True)
    phone_number = Column(String(20), nullable=True)  # Added phone_number
    original_loan_amount = Column(Float, nullable=True)
    original_loan_tenure = Column(Integer, nullable=True)
    current_repayment = Column(Float, nullable=True)
    mode = Column(String(20), nullable=False, default='flow')  # Default value set
    created_at = Column(DateTime, default=lambda: datetime.now(MYT))  # Consistent MYT
    updated_at = Column(DateTime, default=lambda: datetime.now(MYT), onupdate=lambda: datetime.now(MYT))

# ----------------------------
# Users Model
# ----------------------------
class Users(db.Model):
    __tablename__ = 'users'

    id = db.Column(Integer, primary_key=True)
    messenger_id = db.Column(String, nullable=False, unique=True)  # Messenger ID
    sender_id = db.Column(String, nullable=True)  # Optional sender ID
    phone_number = db.Column(String(20), nullable=True)  # Added phone_number
    name = db.Column(String, nullable=True)
    current_step = db.Column(String, nullable=True)
    created_at = db.Column(DateTime, default=lambda: datetime.now(MYT))
    updated_at = db.Column(DateTime, default=lambda: datetime.now(MYT), onupdate=lambda: datetime.now(MYT))

# ----------------------------
# Lead Model
# ----------------------------
class Lead(db.Model):
    __tablename__ = 'leads'

    id = db.Column(Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(Integer, ForeignKey('users.id'), index=True, nullable=False)
    sender_id = db.Column(String(20), nullable=False)
    name = db.Column(String(50), nullable=False)
    property_reference = db.Column(String(50), nullable=True, unique=True)
    original_loan_amount = db.Column(Float, nullable=False)
    original_loan_tenure = db.Column(Integer, nullable=False)
    current_repayment = db.Column(Float, nullable=False)

    # Savings and Calculation Fields
    new_repayment = db.Column(Float, nullable=True)
    monthly_savings = db.Column(Float, nullable=True)
    yearly_savings = db.Column(Float, nullable=True)
    total_savings = db.Column(Float, nullable=True)
    years_saved = db.Column(Integer, nullable=True)

    phone_number = db.Column(String(20), nullable=True)  # Added phone_number

    created_at = db.Column(DateTime, default=lambda: datetime.now(MYT))
    updated_at = db.Column(DateTime, default=lambda: datetime.now(MYT), onupdate=lambda: datetime.now(MYT))

# ----------------------------
# ChatLog Model
# ----------------------------
class ChatLog(db.Model):
    __tablename__ = 'chat_logs'

    id = db.Column(Integer, primary_key=True)
    user_id = db.Column(Integer, ForeignKey('users.id'), nullable=False)
    sender_id = db.Column(String(255), nullable=True)
    name = db.Column(String(255), nullable=True)
    phone_number = db.Column(String(20), nullable=True)  # Changed from String(255) to String(20)
    message_content = db.Column(Text, nullable=False)  # Updated column name
    created_at = db.Column(DateTime, default=lambda: datetime.now(MYT))  # Corrected datetime call

# ----------------------------
# BankRate Model
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
