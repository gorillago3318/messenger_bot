from flask import Blueprint, request, jsonify
from datetime import datetime
from ..extensions import db
from ..models import User, Lead, ChatLog, BankRate
from ..calculation import perform_calculation  # Import the calculation module

chatbot_bp = Blueprint('chatbot', __name__)

# Helper function to send chatbot message response
def send_message(phone_number, message):
    """ Simulate sending a message (could be replaced with actual WhatsApp API) """
    return jsonify({"phone_number": phone_number, "message": message})

@chatbot_bp.route('/start', methods=['POST'])
def start_chat():
    """Welcome message for the user and ask for their name"""
    phone_number = request.json.get('phone_number')
    user = User.query.filter_by(wa_id=phone_number).first()

    if not user:
        user = User(wa_id=phone_number, current_step='get_name')
        db.session.add(user)
    else:
        user.current_step = 'get_name'
    
    db.session.commit()
    
    message = (
        "Hi! Welcome to FinZo, your personal refinancing assistant. 😊\n"
        "Here's how I can help you:\n"
        "- Get an estimation of your potential savings.\n"
        "- Provide personalized guidance for refinancing.\n"
        "\nLet's start by getting your name. Please share your name to proceed.\n"
        "If you make a mistake, you can type 'restart' at any time to start over."
    )
    return send_message(phone_number, message)

@chatbot_bp.route('/restart', methods=['POST'])
def restart_chat():
    """Restart the conversation by clearing user data and sending the welcome message"""
    phone_number = request.json.get('phone_number')
    User.query.filter_by(wa_id=phone_number).delete()
    Lead.query.filter_by(phone_number=phone_number).delete()
    db.session.commit()
    return start_chat()

@chatbot_bp.route('/process_message', methods=['POST'])
def process_message():
    """Process all incoming messages and route them based on current step"""
    data = request.get_json()
    phone_number = data.get('phone_number')
    message_body = data.get('message', '').strip().lower()
    
    if message_body == 'restart':
        return restart_chat()
    
    user = User.query.filter_by(wa_id=phone_number).first()
    
    if not user or not user.current_step:
        return start_chat()
    
    current_step = user.current_step
    
    if current_step == 'get_name':
        return get_name(phone_number, message_body)
    elif current_step == 'get_age':
        return get_age(phone_number, message_body)
    elif current_step == 'get_loan_amount':
        return get_loan_amount(phone_number, message_body)
    elif current_step == 'get_loan_tenure':
        return get_loan_tenure(phone_number, message_body)
    elif current_step == 'get_monthly_repayment':
        return get_monthly_repayment(phone_number, message_body)
    elif current_step == 'get_interest_rate':
        return get_interest_rate(phone_number, message_body)
    elif current_step == 'get_remaining_tenure':
        return get_remaining_tenure(phone_number, message_body)
    else:
        return send_message(phone_number, "I'm not sure how to respond to that. You can ask me questions about refinancing, or type 'restart' to begin.")


def get_name(phone_number, name):
    """Get user name and ask for their age"""
    if name.lower().strip() == 'restart':
        return restart_chat()
    
    if not name.isalpha() or len(name) < 2:
        return send_message(phone_number, "That doesn't look like a valid name. Please provide your name.")
    
    user = User.query.filter_by(wa_id=phone_number).first()
    if not user:
        user = User(wa_id=phone_number, name=name, current_step='get_age')
        db.session.add(user)
    else:
        user.name = name
        user.current_step = 'get_age'
    
    db.session.commit()
    return send_message(phone_number, f"Thanks, {name}! How old are you? (18-70)")


def get_age(phone_number, age):
    """Get user age and ask for current loan amount"""
    if not age.isdigit() or not (18 <= int(age) <= 70):
        return send_message(phone_number, "Please provide a valid age between 18 and 70.")
    
    user = User.query.filter_by(wa_id=phone_number).first()
    if user:
        user.age = int(age)
        user.current_step = 'get_loan_amount'
        db.session.commit()
    
    return send_message(phone_number, "Great! What's your original loan amount? (e.g., 100k, 1.2m)")


def get_interest_rate(phone_number, interest_rate):
    """Get the user's interest rate and proceed to optional remaining tenure"""
    if interest_rate.lower() == 'skip':
        interest_rate = None
    else:
        try:
            interest_rate = float(interest_rate.strip('%'))
        except ValueError:
            return send_message(phone_number, "Please provide the interest rate in a valid format (e.g., 3.5 or 3.5%).")
    
    lead = Lead.query.filter_by(phone_number=phone_number).first()
    if lead:
        lead.interest_rate = interest_rate
        db.session.commit()
    
    user = User.query.filter_by(wa_id=phone_number).first()
    if user:
        user.current_step = 'get_remaining_tenure'
        db.session.commit()
    
    return send_message(phone_number, "If you know your remaining loan tenure, please enter it. Otherwise, type 'skip'.")


def get_remaining_tenure(phone_number, remaining_tenure):
    """Get remaining tenure from the user"""
    if remaining_tenure.lower() == 'skip':
        remaining_tenure = None
    else:
        try:
            remaining_tenure = int(remaining_tenure)
        except ValueError:
            return send_message(phone_number, "Please provide the remaining tenure as a number (e.g., 15).")
    
    lead = Lead.query.filter_by(phone_number=phone_number).first()
    if lead:
        lead.remaining_tenure = remaining_tenure
        db.session.commit()
    
    return send_message(phone_number, "Thank you! We have captured all your information.")


def get_loan_amount(phone_number, loan_amount):
    """Get original loan amount and ask for loan tenure"""
    try:
        if 'k' in loan_amount:
            loan_amount = float(loan_amount.replace('k', '')) * 1000
        elif 'm' in loan_amount:
            loan_amount = float(loan_amount.replace('m', '')) * 1_000_000
        else:
            loan_amount = float(loan_amount)
    except ValueError:
        return send_message(phone_number, "Please provide the loan amount in a valid format (e.g., 100k, 1.2m).")
    
    lead = Lead.query.filter_by(phone_number=phone_number).first()
    if not lead:
        lead = Lead(phone_number=phone_number, original_loan_amount=loan_amount)
        db.session.add(lead)
    else:
        lead.original_loan_amount = loan_amount
    
    user = User.query.filter_by(wa_id=phone_number).first()
    if user:
        user.current_step = 'get_loan_tenure'
    
    db.session.commit()
    return send_message(phone_number, "Thanks! What was the original loan tenure in years? (1-40)")
