# backend/routes/chatbot.py

import os
import re
import logging
import requests
import openai
import json
from flask import Blueprint, request, jsonify
from backend.extensions import db
from backend.models import User, Lead, BankRate
from datetime import datetime

# Initialize Blueprint
chatbot_bp = Blueprint('chatbot', __name__)

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Set OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

# Define the handle_contact_admin function FIRST
def handle_contact_admin(user: User, messenger_id: str, user_input: str):
    """
    Handles the 'I want to talk to admin' payload and sends admin contact details.
    """
    logging.debug("User requested to talk to admin.")

    # Send admin contact details
    message = {
        "text": (
            "You can contact our admin directly at:\n\n"
            "📞 WhatsApp: [Click here to chat](https://wa.me/60126181683)\n\n"
            "Let us know if you need any further assistance!"
        )
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Admin contact details sent to user.")

    # Update state to WAITING_INPUT for follow-up inquiries
    user.state = STATES['WAITING_INPUT']
    db.session.commit()

STATES = {
    'GET_STARTED_YES': 'GET_STARTED_YES',  # New state for starting the process
    'CONTACT_ADMIN': 'CONTACT_ADMIN',      # New state for contacting admin
    'NAME_COLLECTION': 'NAME_COLLECTION',
    'PHONE_COLLECTION': 'PHONE_COLLECTION',
    'PATH_SELECTION': 'PATH_SELECTION',

    # Path A
    'PATH_A_GATHER_BALANCE': 'PATH_A_GATHER_BALANCE',
    'PATH_A_GATHER_INTEREST': 'PATH_A_GATHER_INTEREST',
    'PATH_A_GATHER_TENURE': 'PATH_A_GATHER_TENURE',
    'PATH_A_CALCULATE': 'PATH_A_CALCULATE',

    # Path B
    'PATH_B_GATHER_ORIGINAL_AMOUNT': 'PATH_B_GATHER_ORIGINAL_AMOUNT',
    'PATH_B_GATHER_ORIGINAL_TENURE': 'PATH_B_GATHER_ORIGINAL_TENURE',
    'PATH_B_GATHER_MONTHLY_PAYMENT': 'PATH_B_GATHER_MONTHLY_PAYMENT',
    'PATH_B_GATHER_YEARS_PAID': 'PATH_B_GATHER_YEARS_PAID',
    'PATH_B_CALCULATE': 'PATH_B_CALCULATE',

    # Post-Calculation
    'CASHOUT_OFFER': 'CASHOUT_OFFER',
    'CASHOUT_GATHER_AMOUNT': 'CASHOUT_GATHER_AMOUNT',
    'CASHOUT_CALCULATE': 'CASHOUT_CALCULATE',

    # Additional States
    'FAQ': 'FAQ',
    'END': 'END',
    'WAITING_INPUT': 'WAITING_INPUT',
    'RESTART': 'RESTART',

    # Error Handling
    'ERROR_STATE': 'ERROR_STATE'
}


# Language mapping
LANGUAGES = {'LANG_EN': 'en', 'LANG_MS': 'ms', 'LANG_ZH': 'zh'}

# Load presets.json for FAQs
PRESETS_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'utils', 'presets.json')
)

try:
    with open(PRESETS_FILE, 'r', encoding='utf-8') as f:
        presets_data = json.load(f)
        FAQs = presets_data.get("faqs", [])
except FileNotFoundError:
    logging.error(f"presets.json not found at {PRESETS_FILE}. Ensure the file exists.")
    FAQs = []
except json.JSONDecodeError as e:
    logging.error(f"Error decoding presets.json: {e}")
    FAQs = []

# Helper Functions
def parse_number_with_suffix(user_input: str) -> float:
    """
    Converts inputs like '350k' to 350000, '1.2m' to 1200000, etc.
    """
    text = user_input.lower().replace(",", "").replace(" ", "")
    multiplier = 1
    if 'm' in text:
        multiplier = 1_000_000
        text = text.replace('m', '')
    elif 'k' in text:
        multiplier = 1_000
        text = text.replace('k', '')
    try:
        return float(text) * multiplier
    except ValueError:
        raise ValueError("Invalid number format")

def is_valid_name(name: str) -> bool:
    """
    Validates that the name contains only alphabetic characters and is between 2 and 50 characters.
    """
    return bool(re.fullmatch(r"[A-Za-z\s]{2,50}", name))

def is_valid_phone(phone: str) -> bool:
    """
    Validates Malaysian phone numbers:
    - Starts with '01'
    - Contains only digits
    - Is 10 or 11 digits long
    """
    return bool(re.fullmatch(r"01\d{8,9}", phone))

def is_affirmative(text: str) -> bool:
    """
    Determines if the user's input is affirmative.
    """
    text = text.lower()
    affirmatives = ["yes", "y", "sure", "ok", "okay", "yeah", "ya", "alright", "proceed", "continue", "go ahead"]
    return any(a in text for a in affirmatives)

def calculate_monthly_payment(principal: float, annual_interest_rate: float, years: float) -> float:
    """
    Calculates the monthly payment for a loan.
    """
    if principal <= 0 or annual_interest_rate <= 0 or years <= 0:
        return 0.0
    r = (annual_interest_rate / 100.0) / 12.0
    n = years * 12
    numerator = r * (1 + r)**n
    denominator = (1 + r)**n - 1
    if denominator == 0:
        return 0.0
    monthly = principal * (numerator / denominator)
    return monthly

def estimate_loan_details(original_amount: float, original_tenure: float, current_monthly_payment: float, years_paid: float):
    """
    Estimates outstanding balance and remaining tenure based on inputs.
    """
    guessed_rate = 4.5  # Example fixed rate; consider making this dynamic
    remain_tenure = original_tenure - years_paid
    if remain_tenure < 1:
        remain_tenure = 1

    r = (guessed_rate / 100.0) / 12.0
    n = remain_tenure * 12
    numerator = r * (1 + r)**n
    denominator = (1 + r)**n - 1
    if denominator == 0:
        outstanding_guess = original_amount
    else:
        factor = numerator / denominator
        outstanding_guess = current_monthly_payment / factor

    return guessed_rate, outstanding_guess, remain_tenure

def get_current_bank_rate(loan_size: float) -> float:
    """
    Retrieves the current bank rate based on loan size from the BankRate table.
    Falls back to 3.8% if no matching rate is found.
    """
    try:
        # Check if loan_size is valid
        if loan_size is None or loan_size <= 0:
            logging.error("Loan size is None or invalid. Defaulting to 3.8% rate.")
            return 3.8  # Default rate

        # Query the database for matching rate
        matching_rate = BankRate.query.filter(
            BankRate.min_amount <= loan_size,
            ((BankRate.max_amount >= loan_size) | (BankRate.max_amount.is_(None)))
        ).order_by(BankRate.interest_rate.asc()).first()

        if matching_rate:
            return matching_rate.interest_rate
        else:
            return 3.8  # Fallback rate
    except Exception as e:
        logging.error(f"Error fetching bank rate: {e}")
        return 3.8  # Fallback rate

def send_initial_message(messenger_id):
    message = {
        "text": (
            "👋 Welcome to *Finzo AI Assistant*!\n\n"
            "• I’m here to help you explore *refinancing options*.\n"
            "• We’ll work together to *optimize your housing loans*.\n"
            "• My goal is to help you *identify potential savings* and *improve financial efficiency*.\n\n"
            "Are you ready to get started?"
        ),
        "quick_replies": [
            {
                "content_type": "text",
                "title": "Yes, let's start!",
                "payload": "GET_STARTED_YES"
            },
            {
                "content_type": "text",
                "title": "I want to talk to admin",
                "payload": "CONTACT_ADMIN"
            }
        ]
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Initial welcome message sent.")

def handle_get_started_yes(user: User, messenger_id: str, user_input: str):
    """
    Handles the 'Yes, let's start!' response and proceeds to collect the user's name.
    """
    logging.debug("User selected 'Yes, let's start!'.")

    # Move the user to the NAME_COLLECTION state
    user.state = STATES['NAME_COLLECTION']
    db.session.commit()

    # Ask for the user's name
    message = {
        "text": "Great! What's your *name*?"
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Prompted user to provide name.")

def generate_convincing_message(savings_data: dict) -> str:
    """
    Uses GPT to generate a personalized convincing message based on savings calculations.
    """
    try:
        # Check if savings are below 10k
        if savings_data['total_savings'] < 10000:
            return (
                "Based on your details, the estimated savings from refinancing are below RM10,000. "
                "Considering that refinancing incurs legal fees and stamp duty, it may not be worth the hassle right now. "
                "However, we’re happy to assist if you have any questions or need further guidance. Feel free to reach out at https://wa.me/60126181683."
            )

        # Check if savings are zero or negative
        if savings_data['monthly_savings'] <= 0:
            return (
                "Based on your details, it looks like your current loan is already well-optimized, and refinancing may not result in significant savings. "
                "However, we are here to assist you with any questions or future refinancing needs. Our service is free, and you can always reach out to us at https://wa.me/60126181683 if you'd like more information or need assistance!"
            )

        conversation = [
                {
                "role": "system",
                    "content": (
                        "You are Finzo AI Assistant, an expert in refinancing solutions. Highlight potential savings from refinancing and explain that many homeowners overpay simply due to lack of information about better options. "
                        "Emphasize that this service is completely free, with no hidden fees, and an agent is available to assist unless the user opts out. "
                        "Encourage users to take control of their finances and avoid overpaying unnecessarily, while keeping a professional, friendly, and reassuring tone. "
                        "Avoid greetings or closings like hello or best regards. Focus on presenting benefits clearly and creating urgency without being pushy."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Highlight the savings potential for the user:\n"
                        f"Monthly Savings: RM{savings_data.get('monthly_savings', 0):.2f}\n"
                        f"Yearly Savings: RM{savings_data.get('yearly_savings', 0):.2f}\n"
                        f"Total Savings: RM{savings_data.get('total_savings', 0):.2f} over {savings_data.get('tenure', 0)} years\n"
                        f"Current Interest Rate: {savings_data.get('current_rate', 0):.2f}%\n"
                        f"New Interest Rate: {savings_data.get('new_rate', 0):.2f}%\n"
                        "Frame the message to emphasize how refinancing helps regain financial control and reduce costs. "
                        "Mention that continuing with the current loan benefits the banks, and exploring refinancing options provides the user with better opportunities. "
                        "Encourage questions and emphasize that an agent will assist with more details, maintaining a professional and informative tone."
                    )
                }
            ]


        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=conversation,
            temperature=0.7
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        logging.error(f"Error generating convincing message: {e}")
        return (
            f"You may be overpaying on your home loan. Refinancing at {savings_data.get('new_rate', 0):.2f}% could save you "
            f"RM{savings_data.get('monthly_savings', 0):.2f} monthly and RM{savings_data.get('total_savings', 0):,.2f} over {savings_data.get('tenure', 0)} years. "
            "Our service is completely free, and our agents are here to assist—unless you say 'no,' we'll be in touch to help you explore your savings. Feel free to ask any follow-up questions!"
        )

def generate_faq_response_with_gpt(user_input: str) -> str:
    """
    Uses GPT to generate a response for an unmatched FAQ.
    """
    try:
        conversation = [
            {
                "role": "system",
                "content": (
                    "You are Finzo AI Buddy, a friendly and professional assistant. "
                    "Answer the user's question accurately and concisely."
                )
            },
            {
                "role": "user",
                "content": user_input
            }
        ]

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=conversation,
            temperature=0.7
        )
        gpt_response = response.choices[0].message.content.strip()
        return gpt_response

    except Exception as e:
        logging.error(f"Error generating FAQ response with GPT: {e}")
        return "I'm sorry, I don't have an answer to that. You can ask anything regarding refinancing and housing loans."

# Handler Functions
def handle_language_selection(user: User, messenger_id: str, user_input: str):
    language_map = {
        'LANG_EN': 'en',
        'LANG_MS': 'ms',
        'LANG_ZH': 'zh'
    }

    if user_input in language_map:
        user.language = language_map[user_input]
        user.state = STATES['NAME_COLLECTION']
        db.session.commit()

        question = "Great! What's your *name*?"
        message = {
            "text": question
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Language selected and name collection initiated.")
    else:
        message = {
            "text": "Please select a valid language by clicking one of the options."
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Invalid language selection.")

def handle_name_collection(user: User, messenger_id: str, user_input: str):
    name = user_input.strip()
    if not is_valid_name(name):
        question = "Could you kindly share your *name* again?"
        message = {
            "text": f"Please provide a valid name.\n\n_{question}_"
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Invalid name provided.")
        return

    user.name = name
    user.state = STATES['PHONE_COLLECTION']
    db.session.commit()

    question = "May I have your *phone number* to proceed further?"
    message = {
        "text": f"Nice to meet you, {user.name}! {question}\n\n_Example: 0123456789 (exclude country code)_"
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Name collected and phone number collection initiated.")

def handle_phone_collection(user: User, messenger_id: str, user_input: str):
    phone = re.sub(r"[^\d+]", "", user_input)
    if not is_valid_phone(phone):
        message = {
            "text": "Please provide a *valid Malaysian phone number* starting with '01' and containing 10 or 11 digits."
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Invalid phone number provided.")
        return

    user.phone_number = phone
    user.state = STATES['PATH_SELECTION']
    db.session.commit()

    message = {
        "text": (
            "Do you know your *outstanding balance, interest rate, and remaining tenure?*\n\n"
            "_For more accurate calculations, we suggest checking this info in your bank app before proceeding._"
        ),
        "quick_replies": [
            {
                "content_type": "text",
                "title": "Yes",
                "payload": "KNOW_DETAILS_YES"
            },
            {
                "content_type": "text",
                "title": "No",
                "payload": "KNOW_DETAILS_NO"
            }
        ]
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Phone number collected and path selection initiated.")

def handle_path_selection(user: User, messenger_id: str, user_input: str):
    if user_input == "KNOW_DETAILS_YES":
        user.state = STATES['PATH_A_GATHER_BALANCE']
        db.session.commit()
        question = (
            "Could you share your *outstanding loan amount?*\n\n"
            "_Key in digits, for example:_ *500k* or *500000*"
        )
        message = {"text": question}
        send_messenger_message(messenger_id, message)
        logging.debug("Path A selected: Gather outstanding balance.")
    elif user_input == "KNOW_DETAILS_NO":
        user.state = STATES['PATH_B_GATHER_ORIGINAL_AMOUNT']
        db.session.commit()
        question = (
            "Could you let us know the *original loan amount?*\n\n"
            "_Key in digits, for example:_ *500k* or *500000*"
        )
        message = {"text": question}
        send_messenger_message(messenger_id, message)
        logging.debug("Path B selected: Gather original loan amount.")
    else:
        # Invalid input handling
        message = {"text": "Please select one of the options provided."}
        send_messenger_message(messenger_id, message)
        logging.debug("Invalid path selection input.")


# Path A Handlers
def handle_path_a_balance(user: User, messenger_id: str, user_input: str):
    try:
        balance = parse_number_with_suffix(user_input)
    except ValueError:
        question = "Could you provide your *outstanding loan amount again?*"
        message = {"text": f"Sorry, I couldn't parse that.\n\n{question}"}
        send_messenger_message(messenger_id, message)
        logging.debug("Failed to parse outstanding balance.")
        return

    # Save balance and move to the next step
    user.outstanding_balance = balance
    user.state = STATES['PATH_A_GATHER_INTEREST']
    db.session.commit()

    question = "What is your *current interest rate (in %)*?"
    message = {"text": question}
    send_messenger_message(messenger_id, message)
    logging.debug("Outstanding balance collected and interest rate collection initiated.")

def handle_path_a_interest(user: User, messenger_id: str, user_input: str):
    try:
        interest = float(user_input.replace("%", "").strip())
    except ValueError:
        question = "What is your *current interest rate (in %)?*"
        message = {
            "text": f"Sorry, I couldn't parse that.\n\n{question}\n\n_Example: 4.5 or 4.75_"
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Failed to parse interest rate.")
        return

    user.current_interest_rate = interest
    user.state = STATES['PATH_A_GATHER_TENURE']
    db.session.commit()

    question = "How many *years remain* on your loan tenure?"
    message = {
        "text": f"{question}\n\n_Example: 20 or 25_"
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Interest rate collected and remaining tenure collection initiated.")

def handle_path_a_tenure(user: User, messenger_id: str, user_input: str):
    try:
        tenure = float(re.sub(r"[^\d\.]", "", user_input))
    except ValueError:
        question = "Could you provide the *remaining tenure (in years) again?*"
        message = {
            "text": f"Sorry, I couldn't parse that.\n\n{question}\n\n_Example: 10 or 15_"
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Failed to parse remaining tenure.")
        return

    user.remaining_tenure = tenure
    user.state = STATES['PATH_A_CALCULATE']
    db.session.commit()

    handle_path_a_calculate(user, messenger_id)
    logging.debug("Remaining tenure collected and Path A calculation initiated.")


def handle_path_a_calculate(user: User, messenger_id: str, *args):
    """
    Handles the calculation step in Path A after gathering all necessary inputs.
    """
    logging.debug("Entering handle_path_a_calculate function.")

    balance = user.outstanding_balance
    interest = user.current_interest_rate
    tenure = user.remaining_tenure

    if balance is None or interest is None or tenure is None:
        send_messenger_message(messenger_id, {"text": "I'm missing data. Type 'restart' or re-enter details."})
        logging.error("Missing data for Path A calculation.")
        return

    new_rate = get_current_bank_rate(balance)
    current_monthly = calculate_monthly_payment(balance, interest, tenure)
    new_monthly = calculate_monthly_payment(balance, new_rate, tenure)

    monthly_savings = current_monthly - new_monthly
    yearly_savings = monthly_savings * 12
    total_savings = monthly_savings * tenure * 12

    user.monthly_savings = monthly_savings
    user.yearly_savings = yearly_savings
    user.total_savings = total_savings
    user.tenure = tenure
    user.current_interest_rate = interest
    user.new_rate = new_rate

    db.session.commit()

    # Send calculation summary
    summary = (
        f"🏦 *Current Loan:*\n"
        f"• Monthly Payment: RM{current_monthly:,.2f}\n"
        f"• Interest Rate: {interest:.2f}%\n\n"
        f"💰 *After Refinancing:*\n"
        f"• New Monthly Payment: RM{new_monthly:,.2f}\n"
        f"• New Interest Rate: {new_rate:.2f}%\n\n"
        f"🎯 *Your Savings:*\n"
        f"• Monthly: RM{monthly_savings:,.2f}\n"
        f"• Yearly: RM{yearly_savings:,.2f}\n"
        f"• Total: RM{total_savings:,.2f} over {int(tenure)} years\n\n"
        f"Finzo AI is analyzing your refinance details to determine if it’s beneficial. Please hold on for a moment."
    )

    # **Correction:** Remove the nested "message" key
    send_messenger_message(messenger_id, {"text": summary})
    logging.debug("Path A calculation summary sent.")

    # Invoke handle_convince once to send the convince message and cash-out prompt
    handle_convince(user, messenger_id)
    logging.debug("handle_convince manually invoked after Path A calculation.")

# Path B Handlers
def handle_path_b_original_amount(user: User, messenger_id: str, user_input: str):
    try:
        amt = parse_number_with_suffix(user_input)
    except ValueError:
        message = {
            "text": "Could you please provide the original loan amount again?"
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Failed to parse original loan amount.")
        return

    user.original_amount = amt
    user.state = STATES['PATH_B_GATHER_ORIGINAL_TENURE']
    db.session.commit()

    message = {
        "text": "May I know the *original loan tenure* in years?"
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Original loan amount collected and original tenure collection initiated.")

def handle_path_b_original_tenure(user: User, messenger_id: str, user_input: str):
    try:
        tenure = parse_number_with_suffix(user_input)
    except ValueError:
        message = {
            "text": "Could you please provide the original tenure in years again?"
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Failed to parse original loan tenure.")
        return

    user.original_tenure = tenure
    user.state = STATES['PATH_B_GATHER_MONTHLY_PAYMENT']
    db.session.commit()

    message = {
        "text": "What is your *current monthly payment?*"
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Original loan tenure collected and monthly payment collection initiated.")

def handle_path_b_monthly_payment(user: User, messenger_id: str, user_input: str):
    try:
        monthly = parse_number_with_suffix(user_input)
    except ValueError:
        message = {
            "text": "Could you please provide the current monthly payment again?"
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Failed to parse current monthly payment.")
        return

    user.current_monthly_payment = monthly
    user.state = STATES['PATH_B_GATHER_YEARS_PAID']
    db.session.commit()

    message = {
        "text": "How many *years have you paid so far?*"
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Current monthly payment collected and years paid collection initiated.")

def handle_path_b_years_paid(user: User, messenger_id: str, user_input: str):
    try:
        yrs = parse_number_with_suffix(user_input)
    except ValueError:
        message = {
            "text": "Could you please let us know how many years you have paid so far?"
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Failed to parse years paid.")
        return

    user.years_paid = yrs
    user.state = STATES['PATH_B_CALCULATE']
    db.session.commit()
    handle_path_b_calculate(user, messenger_id)
    logging.debug("Years paid collected and Path B calculation initiated.")

def handle_path_b_calculate(user: User, messenger_id: str, *args):
    """
    Handles the calculation step in Path B after gathering all necessary inputs.
    """
    logging.debug("Entering handle_path_b_calculate function.")

    # Retrieve user inputs
    orig_amt = user.original_amount
    orig_tenure = user.original_tenure
    monthly_payment = user.current_monthly_payment
    yrs_paid = user.years_paid

    # Validate inputs
    if any(v is None for v in [orig_amt, orig_tenure, monthly_payment, yrs_paid]):
        send_messenger_message(messenger_id, {"text": "Some data is missing. Please type 'restart' or re-enter the required details."})
        logging.error("Missing data for Path B calculation.")
        return

    # Perform loan estimations
    guessed_rate, current_outstanding, remain_tenure = estimate_loan_details(
        orig_amt, orig_tenure, monthly_payment, yrs_paid
    )

    # Get new interest rate based on outstanding balance
    new_rate = get_current_bank_rate(current_outstanding)
    
    # Calculate monthly payments
    current_monthly_calc = calculate_monthly_payment(current_outstanding, guessed_rate, remain_tenure)
    new_monthly_calc = calculate_monthly_payment(current_outstanding, new_rate, remain_tenure)

    # Calculate savings
    monthly_savings = current_monthly_calc - new_monthly_calc
    yearly_savings = monthly_savings * 12
    total_savings = monthly_savings * remain_tenure * 12

    # Update user attributes
    user.monthly_savings = monthly_savings
    user.yearly_savings = yearly_savings
    user.total_savings = total_savings
    user.tenure = remain_tenure
    user.current_interest_rate = guessed_rate  # Ensure consistency
    user.new_rate = new_rate
    user.outstanding_balance = current_outstanding

    db.session.commit()

    logging.debug("Path B calculation details updated for user.")

    # Send calculation summary
    summary = (
        f"🏦 *Current Loan:*\n"
        f"• Monthly Payment: RM{current_monthly_calc:,.2f}\n"
        f"• Estimated Interest Rate: {guessed_rate:.2f}%\n\n"
        f"💰 *After Refinancing:*\n"
        f"• New Monthly Payment: RM{new_monthly_calc:,.2f}\n"
        f"• New Interest Rate: {new_rate:.2f}%\n\n"
        f"🎯 *Your Savings:*\n"
        f"• Monthly: RM{monthly_savings:,.2f}\n"
        f"• Yearly: RM{yearly_savings:,.2f}\n"
        f"• Total: RM{total_savings:,.2f} over {int(remain_tenure)} years\n\n"
        f"Finzo AI is analyzing your refinance details to determine if it’s beneficial. Please hold on for a moment."

    )

    # **Correction:** Remove the nested "message" key
    send_messenger_message(messenger_id, {"text": summary})
    logging.debug("Path B calculation summary sent.")

    # Invoke handle_convince once to send the convince message and cash-out prompt
    handle_convince(user, messenger_id)
    logging.debug("handle_convince manually invoked after Path B calculation.")

def handle_convince(user: User, messenger_id: str, user_input: str = ""):
    """
    Sends the convincing message and cash-out prompt to the user.
    """
    logging.debug("Entering handle_convince function.")

    # Prepare savings data with default values to prevent NoneType errors
    savings_data = {
        'monthly_savings': user.monthly_savings or 0,
        'yearly_savings': user.yearly_savings or 0,
        'total_savings': user.total_savings or 0,
        'tenure': user.remaining_tenure or user.tenure or 0,
        'current_rate': user.current_interest_rate or 0,
        'new_rate': user.new_rate or 0
    }

    logging.debug(f"Savings Data: {savings_data}")

    # Generate the convincing message
    convincing_msg = generate_convincing_message(savings_data)
    
    # **Correction:** Remove the nested "message" key
    send_messenger_message(messenger_id, {"text": convincing_msg})
    logging.debug("Convincing message sent.")

    # Prepare the Cash-Out Prompt with quick replies
    cashout_message = (
        "Are you interested in exploring cash-out refinancing options?\n\n"
        "Cash-out refinancing allows you to access extra funds by tapping into your home equity. "
        "It’s a flexible way to finance important expenses while consolidating your existing mortgage.\n\n"
        "You can use the additional funds for purposes such as:\n"
        "• Home renovations or upgrades\n"
        "• Education and tuition fees\n"
        "• Investment opportunities\n"
        "• Consolidating debts for better financial management\n\n"
        "_*Note: According to Bank Negara Malaysia (BNM) guidelines, cash-out refinancing is limited "
        "to a maximum repayment period of 10 years or up to 70 years of age, whichever comes first._*"
    )

    quick_replies = [
        {"content_type": "text", "title": "Yes, tell me more", "payload": "CASHOUT_YES"},
        {"content_type": "text", "title": "No, thanks", "payload": "CASHOUT_NO"}
    ]

    # **Correction:** Remove the nested "message" key
    send_messenger_message(messenger_id, {"text": cashout_message, "quick_replies": quick_replies})
    logging.debug("Cash-out prompt sent.")

    # Update user state to CASHOUT_OFFER
    user.state = STATES['CASHOUT_OFFER']
    db.session.commit()
    logging.debug(f"User state updated to {user.state}")

def handle_cashout_offer(user: User, messenger_id: str, user_input: str):
    """
    Handles the user's response to the cash-out offer.
    """
    logging.debug("Entering handle_cashout_offer function.")

    if user_input is None:
        # Send cash-out offer prompt
        message = {
            "text": "Would you like to proceed with a cash-out refinance offer?",
            "quick_replies": [
                {
                    "content_type": "text",
                    "title": "Yes, tell me more",
                    "payload": "CASHOUT_YES"
                },
                {
                    "content_type": "text",
                    "title": "No, thanks",
                    "payload": "CASHOUT_NO"
                }
            ]
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Cash-out offer prompt sent to user.")
        return

    # Handle user response
    if user_input == "CASHOUT_YES":
        # Transition to gather cash-out amount
        user.state = STATES['CASHOUT_GATHER_AMOUNT']
        db.session.commit()
        question = (
            "Great! How much equity would you like to cash out from your property in *Ringgit?*\n\n "
        "_For example, RM50,000 or 50k._"
        )
        send_messenger_message(messenger_id, {"text": question})
        logging.debug("User accepted cash-out offer. Cash-out amount collection initiated.")
    elif user_input == "CASHOUT_NO":
        # Transition to WAITING_INPUT without cash-out
        user.temp_cashout_amount = 0  # No cash-out
        user.state = STATES['WAITING_INPUT']
        db.session.commit()

        # Notify admin about declined cash-out offer
        admin_summary = (
            f"📊 User Declined Cash-Out Offer\n"
            f"Customer: {user.name or 'N/A'}\n"
            f"Contact: {user.phone_number or 'N/A'}\n\n"
            f"📊 Loan Details:\n"
            f"• Outstanding Balance: RM{user.outstanding_balance or 0:,.2f}\n"
            f"• Interest Rate: {user.current_interest_rate or 0:.2f}%\n"
            f"• Remaining Tenure: {user.remaining_tenure or 0:.1f} years\n\n"
            f"After Refinancing:\n"
            f"• New Interest Rate: {user.new_rate or 0:.2f}%\n"
            f"• Monthly Savings: RM{user.monthly_savings or 0:.2f}\n"
            f"• Yearly Savings: RM{user.yearly_savings or 0:.2f}\n"
            f"• Total Savings: RM{user.total_savings or 0:.2f}\n"
            f"• Tenure: {user.tenure or 0:.1f} years\n\n"
            f"📊 Cash-Out Calculation:\n"
            f"• Main Loan: RM{user.outstanding_balance or 0:,.2f} @ {user.new_rate or 0:.2f}% for {int(user.remaining_tenure or 0)} yrs => RM{calculate_monthly_payment(user.outstanding_balance or 0, user.new_rate or 0, user.remaining_tenure or 0):,.2f}/month\n"
            f"• Cash-Out: RM{user.temp_cashout_amount or 0:,.2f} @ {user.new_rate or 0:.2f}% for 10 yrs => RM{calculate_monthly_payment(user.temp_cashout_amount or 0, user.new_rate or 0, 10):,.2f}/month\n\n"
            f"💳 Total Monthly Payment: RM{(calculate_monthly_payment(user.outstanding_balance or 0, user.new_rate or 0, user.remaining_tenure or 0) + calculate_monthly_payment(user.temp_cashout_amount or 0, user.new_rate or 0, 10)) or 0:,.2f}\n\n"
            f"Status: {'Accepted Cash-Out Offer' if (user.temp_cashout_amount or 0) > 0 else 'Declined Cash-Out Offer'}"
        )
        notify_admin(user, "User Declined Cash-Out Offer", admin_summary)
        logging.debug("User declined cash-out offer and admin notified.")

        # FAQ Prompt
        faq_prompt = (
            "You are now talking to Finzo AI. You can ask anything regarding refinancing and housing loans.\n\n"
            "Common questions you might have:\n"
            "• What documents do I need for refinancing?\n"
            "• How long does the refinancing process take?\n"
            "• Are there any fees involved?\n"
            "• What factors affect my loan approval?"
        )
        send_messenger_message(messenger_id, {"text": faq_prompt})
        logging.debug("FAQ prompt sent after declining cash-out offer.")
    else:
        # Handle unexpected inputs
        send_messenger_message(messenger_id, {"text": "Please select 'Yes, tell me more' or 'No, thanks'."})
        logging.debug("Unexpected input received for cash-out offer.")

def handle_cashout_gather_amount(user: User, messenger_id: str, user_input: str):
    logging.debug("Entering handle_cashout_gather_amount function.")

    try:
        # Corrected function call
        cashout_amount = parse_number_with_suffix(user_input)
        user.temp_cashout_amount = cashout_amount
        db.session.commit()
        logging.debug(f"Cash-out amount {cashout_amount} set for user.")

        # Proceed to calculate the new loan details
        handle_cashout_calculate(user, messenger_id)

    except Exception as e:
        logging.error(f"Error gathering cash-out amount: {e}")
        send_messenger_message(
            messenger_id,
            {"text": "I'm sorry, I couldn't process that amount. Please enter a valid cash-out amount in Ringgit (e.g., RM50,000 or 50k)."}
        )
        logging.debug("Error occurred while gathering cash-out amount. Informed user.")

def handle_cashout_calculate(user: User, messenger_id: str, user_input: str = None):
    """
    Calculates cash-out refinancing details and sends results to the user and admin.
    """
    logging.debug("Entering handle_cashout_calculate function.")

    # Get user inputs
    outstanding_balance = user.outstanding_balance or 0.0
    remaining_tenure = user.remaining_tenure or 30
    cashout_amount = user.temp_cashout_amount or 0.0

    # Calculate loan details
    total_loan = outstanding_balance + cashout_amount
    main_rate = get_current_bank_rate(total_loan)  # Assuming this function exists

    # Calculate installments
    segment1_tenure = min(remaining_tenure, 35)
    monthly1 = calculate_monthly_payment(outstanding_balance, main_rate, segment1_tenure)
    monthly2 = calculate_monthly_payment(cashout_amount, main_rate, 10)

    new_total_monthly = monthly1 + monthly2

    # --- Message for USER ---
    user_summary = (
        f"📊 Cash-Out Calculation:\n"
        f"• Main Loan: RM{outstanding_balance:,.2f} @ {main_rate:.2f}% for {segment1_tenure} yrs => RM{monthly1:,.2f}/month\n"
        f"• Cash-Out: RM{cashout_amount:,.2f} @ {main_rate:.2f}% for 10 yrs => RM{monthly2:,.2f}/month\n\n"
        f"💳 Total Monthly Payment: RM{new_total_monthly:,.2f}\n\n"
        f"Note: This is your updated estimated monthly repayment amount if the refinance and cash-out are approved and accepted."
    )
    # **Correction:** Remove the nested "message" key
    send_messenger_message(messenger_id, {"text": user_summary})
    logging.debug("Cash-out calculation summary sent to user.")

    # Transition to WAITING_INPUT instead of FAQ
    user.state = STATES['WAITING_INPUT']
    db.session.commit()

    # FAQ Prompt
    faq_prompt = (
        "The calculation of your savings summary is now completed!\n\n"
        "An agent will be assigned to assist you with the refinancing process at no additional cost. Should you prefer not to proceed, you may inform our agents at any time.\n\n"
        "We are now in the *Inquiry Phase*, where you can interact with Finzo AI to ask any questions about refinancing or housing loans.\n\n"
        "Finzo AI will do our best to provide helpful answers. However, please note that while we strive for accuracy, some answers may not be 100% precise.\n\n"
        "For urgent matters, you can also contact our admin at https://wa.me/60126181683."
    )
    send_messenger_message(messenger_id, {"text": faq_prompt})
    logging.debug("FAQ prompt sent after cash-out calculation.")

    # Send admin notification
    admin_summary = (
        f"📊 Loan and Cash-Out Details:\n"
        f"• Customer: {user.name}\n"
        f"• Contact: {user.phone_number}\n\n"
        f"Current Loan:\n"
        f"• Outstanding Balance: RM{user.outstanding_balance:,.2f}\n"
        f"• Interest Rate: {user.current_interest_rate:.2f}%\n"
        f"• Remaining Tenure: {user.remaining_tenure:.1f} years\n\n"
        f"After Refinancing:\n"
        f"• New Interest Rate: {user.new_rate:.2f}%\n"
        f"• Monthly Savings: RM{user.monthly_savings:.2f}\n"
        f"• Yearly Savings: RM{user.yearly_savings:.2f}\n"
        f"• Total Savings: RM{user.total_savings:.2f}\n"
        f"• Tenure: {user.tenure:.1f} years\n\n"
        f"📊 Cash-Out Calculation:\n"
        f"• Main Loan: RM{outstanding_balance:,.2f} @ {main_rate:.2f}% for {segment1_tenure} yrs => RM{monthly1:,.2f}/month\n"
        f"• Cash-Out: RM{cashout_amount:,.2f} @ {main_rate:.2f}% for 10 yrs => RM{monthly2:,.2f}/month\n\n"
        f"💳 Total Monthly Payment: RM{new_total_monthly:,.2f}\n\n"
        f"Status: {'Accepted Cash-Out Offer' if cashout_amount > 0 else 'Declined Cash-Out Offer'}"
    )
    notify_admin(user, "User Completed Cash-Out Refinance Calculation", admin_summary)
    logging.debug("Admin notified about completed cash-out refinance calculation.")

def handle_waiting_input(user: User, messenger_id: str, user_input: str):
    """
    Handles general user queries after cash-out calculation using GPT-3.5-turbo.
    """
    logging.debug("Entering handle_waiting_input function.")

    # Prepare context with safe formatting
    context = (
        f"Previous Summary:\n"
        f"Monthly Savings: RM{user.monthly_savings or 0:,.2f}\n"
        f"Yearly Savings: RM{user.yearly_savings or 0:,.2f}\n"
        f"Total Savings: RM{user.total_savings or 0:,.2f}\n"
        f"Interest Rate: {user.current_interest_rate or 0:.2f}% -> {user.new_rate or 0:.2f}%\n"
        f"Remaining Tenure: {user.remaining_tenure or user.tenure or 0} years\n"
    )

    try:
        conversation = [
            {
                "role": "system",
                "content": (
                    "You are Finzo AI Buddy, an expert in refinancing and loan advisory. "
                    "Answer user questions based on their previous calculations. "
                    "Use the following context to guide responses:\n"
                    f"{context}"
                )
            },
            {
                "role": "user",
                "content": user_input
            }
        ]

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=conversation,
            temperature=0.7
        )

        reply = response.choices[0].message.content.strip()
        # **Correction:** Remove the nested "message" key
        send_messenger_message(messenger_id, {"text": reply})
        logging.debug("User question processed and response sent.")

    except Exception as e:
        logging.error(f"Error processing user question: {e}")
        send_messenger_message(
            messenger_id,
            {"text": "I'm sorry, I couldn't process your request. An agent will follow up shortly to assist you."}
        )
        logging.debug("Error occurred while processing user question. Informed user.")

    # Remain in the same state to allow further questions
    user.state = STATES['WAITING_INPUT']
    db.session.commit()
    logging.debug("User state remains at WAITING_INPUT.")

def handle_faq(user: User, messenger_id: str, user_input: str):
    """
    Handles FAQ queries, leveraging GPT-3.5-turbo for dynamic responses and preserving session details.
    """
    logging.debug("Entering handle_faq function.")

    # Debug logs to check database values
    logging.debug(f"Monthly Savings: {user.monthly_savings}")
    logging.debug(f"Yearly Savings: {user.yearly_savings}")
    logging.debug(f"Total Savings: {user.total_savings}")
    logging.debug(f"Interest Rate: {user.current_interest_rate}")
    logging.debug(f"New Rate: {user.new_rate}")
    logging.debug(f"Remaining Tenure: {user.remaining_tenure}")

    # Check for admin or agent request
    if any(word in user_input.lower() for word in ['admin', 'agent', 'contact']):
        send_messenger_message(messenger_id, {"text": "You can reach our admin directly at https://wa.me/60126181683 for assistance."})
        logging.debug("User requested admin or agent contact.")
        return

    # Load previous summary and cash-out details if available, fallback to 0 if None
    context = (
        f"Previous Summary:\n"
        f"Monthly Savings: RM{user.monthly_savings or 0:,.2f}\n"
        f"Yearly Savings: RM{user.yearly_savings or 0:,.2f}\n"
        f"Total Savings: RM{user.total_savings or 0:,.2f}\n"
        f"Interest Rate: {user.current_interest_rate or 0:.2f}% -> {user.new_rate or 0:.2f}%\n"
        f"Remaining Tenure: {user.remaining_tenure or user.tenure or 0} years\n"
    )

    try:
        conversation = [
            {
                "role": "system",
                "content": (
                    "You are Finzo AI Buddy, an expert in refinancing and loan advisory. "
                    "Answer user questions based on their previous calculations. "
                    "Use the following context to guide responses:\n"
                    f"{context}"
                )
            },
            {
                "role": "user",
                "content": user_input
            }
        ]

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=conversation,
            temperature=0.7
        )

        reply = response.choices[0].message.content.strip()
        # **Correction:** Remove the nested "message" key
        send_messenger_message(messenger_id, {"text": reply})
        logging.debug("FAQ response generated and sent to user.")

    except Exception as e:
        logging.error(f"Error handling FAQ: {e}")
        send_messenger_message(messenger_id, {"text": "I'm sorry, I couldn't process your request. An agent will follow up shortly to assist you."})
        logging.debug("Error occurred while handling FAQ. Informed user.")

    # Keep session active
    user.state = STATES['WAITING_INPUT']
    db.session.commit()

    # Notify admin for manual follow-up
    notify_admin(user, f"FAQ query received: {user_input}")
    logging.debug("Admin notified about FAQ query.")

# Admin Notification Function
def notify_admin(user: User, event_name: str, summary: str = None):
    """
    Sends an admin notification with loan comparison details.
    """
    admin_id = os.getenv("ADMIN_MESSENGER_ID")
    if not admin_id or not admin_id.isdigit():
        logging.warning(f"No valid ADMIN_MESSENGER_ID set. Skipping notify_admin.")
        return

    if summary:
        # If a summary is provided, include it in the admin notification
        comparison = (
            f"📊 {event_name}\n"
            f"Customer: {user.name or 'N/A'}\n"
            f"Contact: {user.phone_number or 'N/A'}\n\n"
            f"{summary}"
        )
    else:
        # Basic notification without summary
        comparison = (
            f"📊 {event_name}\n"
            f"Customer: {user.name}\n"
            f"Contact: {user.phone_number}\n"
            f"State: {user.state}\n"
            "No loan calculation details available yet."
        )

    send_messenger_message(admin_id, {"text": comparison})
    logging.debug("Admin notification sent.")

# Unhandled State Handler
def handle_unhandled_state(user: User, messenger_id: str, user_input: str):
    """
    Handles any unhandled states gracefully.
    """
    message = {
        "text": "I'm not sure how to handle that. Type 'restart' to start over."
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Unhandled state encountered. Prompted user to restart.")

    # Optionally, reset the user state to a known state
    user.state = STATES['END']
    db.session.commit()

# Messaging Functions
def send_initial_message(messenger_id):
    message = {
        "text": (
            "👋 Welcome to *Finzo AI Assistant*!\n\n"
            "• I’m here to help you explore *refinancing options*.\n"
            "• We’ll work together to *optimize your housing loans*.\n"
            "• My goal is to help you *identify potential savings* and *improve financial efficiency*.\n\n"
            "Are you ready to get started?"
        ),
        "quick_replies": [
            {
                "content_type": "text",
                "title": "Yes, let's start!",
                "payload": "GET_STARTED_YES"
            },
            {
                "content_type": "text",
                "title": "Contact Admin",
                "payload": "CONTACT_ADMIN"
            }
        ]
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Initial welcome message sent with default language set to English.")



def send_messenger_message(recipient_id, message):
    """
    Sends a message to the user via Facebook Messenger API.

    Parameters:
    - recipient_id (str): The Facebook ID of the recipient.
    - message (dict): The message payload containing 'text' and optionally 'quick_replies'.
    """
    try:
        logging.debug(f"Recipient ID: {recipient_id}")
        url = f"https://graph.facebook.com/v16.0/me/messages?access_token={os.getenv('PAGE_ACCESS_TOKEN')}"
        headers = {"Content-Type": "application/json"}

        # Validate message format
        if isinstance(message, str):
            # Simple text message
            data = {
                "recipient": {"id": recipient_id},
                "message": {"text": message}
            }
        elif isinstance(message, dict):
            # Message with quick replies or attachments
            data = {
                "recipient": {"id": recipient_id},
                "message": message
            }
        else:
            raise ValueError("Invalid message format!")

        logging.debug(f"Sending payload: {json.dumps(data, indent=4)}")

        # Send the request
        resp = requests.post(url, json=data, headers=headers)
        logging.debug(f"Response status: {resp.status_code}")
        logging.debug(f"Response body: {resp.text}")
        resp.raise_for_status()

    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send message: {e}")
    except ValueError as ve:
        logging.error(f"Message formatting error: {ve}")

STATE_HANDLERS = {
    STATES['GET_STARTED_YES']: handle_get_started_yes,  # New handler for getting started
    STATES['CONTACT_ADMIN']: handle_contact_admin,      # New handler for contacting admin

    # Name and Phone Collection
    STATES['NAME_COLLECTION']: handle_name_collection,
    STATES['PHONE_COLLECTION']: handle_phone_collection,
    STATES['PATH_SELECTION']: handle_path_selection,

    # Path A
    STATES['PATH_A_GATHER_BALANCE']: handle_path_a_balance,
    STATES['PATH_A_GATHER_INTEREST']: handle_path_a_interest,
    STATES['PATH_A_GATHER_TENURE']: handle_path_a_tenure,
    STATES['PATH_A_CALCULATE']: handle_path_a_calculate,

    # Path B
    STATES['PATH_B_GATHER_ORIGINAL_AMOUNT']: handle_path_b_original_amount,
    STATES['PATH_B_GATHER_ORIGINAL_TENURE']: handle_path_b_original_tenure,
    STATES['PATH_B_GATHER_MONTHLY_PAYMENT']: handle_path_b_monthly_payment,
    STATES['PATH_B_GATHER_YEARS_PAID']: handle_path_b_years_paid,
    STATES['PATH_B_CALCULATE']: handle_path_b_calculate,

    # After calculations
    STATES['CASHOUT_OFFER']: handle_cashout_offer,
    STATES['CASHOUT_GATHER_AMOUNT']: handle_cashout_gather_amount,
    STATES['CASHOUT_CALCULATE']: handle_cashout_calculate,

    # Additional States
    STATES['WAITING_INPUT']: handle_waiting_input,
    STATES['FAQ']: handle_faq,
    STATES['END']: handle_unhandled_state
}

# Main Route to Process Messages
@chatbot_bp.route('/webhook', methods=['POST'])
def process_message():
    try:
        data = request.get_json()
        logging.debug(f"Received data: {data}")

        messaging_events = data.get('entry', [])[0].get('messaging', [])
        if not messaging_events:
            logging.debug("No messaging events found in the received data.")
            return jsonify({"status": "no messaging events"}), 200

        for event in messaging_events:
            sender_id = str(event['sender']['id']).strip()
            message = event['message']

            # Check if the message contains a quick_reply
            if 'quick_reply' in message:
                user_input = message['quick_reply']['payload']
                logging.debug(f"Received quick_reply payload: {user_input}")
            else:
                user_input = message.get('text', '').strip()
                logging.debug(f"Received text: {user_input}")

            if not sender_id or not sender_id.isdigit():
                logging.error("Invalid messenger ID.")
                continue  # Skip to the next event

            # Check if user exists, else create new user
            user = User.query.filter_by(messenger_id=sender_id).first()
            if not user:
                # Create new user with default state
                user = User(
                    messenger_id=sender_id,
                    name="Unknown",
                    phone_number="Unknown",
                    language='en',  # Default to English
                    state=STATES['GET_STARTED_YES']  # Start with name collection
                )
                db.session.add(user)
                db.session.commit()

                send_initial_message(sender_id)
                logging.debug("New user created and initial message sent.")
                continue  # Move to the next event

            # Handle 'restart' command at any time
            if user_input.lower() == 'restart':
                reset_user(user)
                send_initial_message(sender_id)
                logging.debug("User initiated restart. State reset and initial message sent.")
                continue  # Move to the next event

            # Handle "CONTACT_ADMIN" payload
            if user_input == "CONTACT_ADMIN":
                handle_contact_admin(user, sender_id, user_input)
                continue  # Skip further processing

            # Handle "GET_STARTED_YES" payload
            if user_input == "GET_STARTED_YES":
                handle_get_started_yes(user, sender_id, user_input)
                continue  # Skip further processing

            # Fallback to the current state if undefined
            if not user.state:
                user.state = STATES['GET_STARTED_YES']  # Default state is to collect name
                db.session.commit()
                logging.debug("User state was None. Set to GET_STARTED_YES.")

            # MAIN LOGIC FLOW
            state_handler = STATE_HANDLERS.get(user.state, handle_unhandled_state)
            state_handler(user, sender_id, user_input)

        return jsonify({"status": "success"}), 200

    except Exception as e:
        logging.error(f"Error in process_message: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    
def reset_user(user: User):
    """
    Resets the user's information to start over with English as the default language.
    """
    user.name = "Unknown"
    user.phone_number = "Unknown"
    user.language = 'en'  # Default language set to English
    user.state = STATES['GET_STARTED_YES']  # Default to the first step
    # Reset other relevant fields
    user.outstanding_balance = None
    user.current_interest_rate = None
    user.remaining_tenure = None
    user.original_amount = None
    user.original_tenure = None
    user.current_monthly_payment = None
    user.years_paid = None
    user.temp_cashout_amount = None
    user.monthly_savings = None
    user.yearly_savings = None
    user.total_savings = None
    user.tenure = None
    user.new_rate = None
    db.session.commit()
    logging.debug("User data reset to initial state with default language set to English.")

