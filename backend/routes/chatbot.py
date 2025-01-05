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
from datetime import datetime, timedelta
import time



# Initialize Blueprint
chatbot_bp = Blueprint('chatbot', __name__)

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Set OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY").strip()

# Define the handle_contact_admin function FIRST
def handle_contact_admin(user: User, messenger_id: str, user_input: str):
    """
    Handles the 'I want to talk to admin' payload and sends admin contact details.
    """
    logging.debug("User requested to talk to admin.")

    # Use GPT-4 to process admin requests
    try:
        conversation = [
            {
                "role": "system",
                "content": (
                    "You are Finzo AI Assistant. If a user asks for an admin, agent, or human, provide the contact link: https://wa.me/60126181683. "
                    "Maintain a professional, friendly tone and encourage reaching out if needed."
                )
            },
            {
                "role": "user",
                "content": user_input
            }
        ]

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=conversation,
            temperature=0.7
        )

        admin_message = response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Error generating admin message with GPT-4: {e}")
        admin_message = (
            "You can contact our admin directly at:\n\n"
            "\ud83d\udcde WhatsApp: [Click here to chat](https://wa.me/60126181683)\n\n"
            "Let us know if you need any further assistance!"
        )

    send_messenger_message(messenger_id, {"text": admin_message})
    logging.debug("Admin contact details sent to user.")

    # Update state to WAITING_INPUT for follow-up inquiries
    user.state = STATES['WAITING_INPUT']
    db.session.commit()

STATES = {
    'GET_STARTED_YES': 'GET_STARTED_YES',
    'CONTACT_ADMIN': 'CONTACT_ADMIN',
    'NAME_COLLECTION': 'NAME_COLLECTION',
    'PHONE_COLLECTION': 'PHONE_COLLECTION',
    'PATH_SELECTION': 'PATH_SELECTION',
    'PATH_A_GATHER_BALANCE': 'PATH_A_GATHER_BALANCE',
    'PATH_A_GATHER_INTEREST': 'PATH_A_GATHER_INTEREST',
    'PATH_A_GATHER_TENURE': 'PATH_A_GATHER_TENURE',
    'PATH_A_CALCULATE': 'PATH_A_CALCULATE',
    'PATH_B_GATHER_ORIGINAL_AMOUNT': 'PATH_B_GATHER_ORIGINAL_AMOUNT',
    'PATH_B_GATHER_ORIGINAL_TENURE': 'PATH_B_GATHER_ORIGINAL_TENURE',
    'PATH_B_GATHER_MONTHLY_PAYMENT': 'PATH_B_GATHER_MONTHLY_PAYMENT',
    'PATH_B_GATHER_YEARS_PAID': 'PATH_B_GATHER_YEARS_PAID',
    'PATH_B_CALCULATE': 'PATH_B_CALCULATE',
    'FAQ': 'FAQ',
    'END': 'END',
    'WAITING_INPUT': 'WAITING_INPUT',
    'RESTART': 'RESTART',
    'ERROR_STATE': 'ERROR_STATE'
}

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
            "👋 Welcome to Finzo AI Assistant!\n\n"
            "• I’m here to help you explore refinancing options.\n"
            "• We’ll work together to optimize your housing loans.\n"
            "• My goal is to help you identify potential savings and improve financial efficiency.\n\n"
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
        "text": "Great! Can we please get your name?"
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Prompted user to provide name.")

def generate_convincing_message(savings_data: dict) -> str:
    """
    Uses GPT-4 to generate a personalized convincing message based on savings calculations.
    """
    try:
        # Highlight the most important aspect first - Savings Analysis
        savings_message = (
            f"Based on the details you've provided, refinancing could save you approximately RM{savings_data.get('monthly_savings', 0):,.2f} per month. "
            f"That's RM{savings_data.get('yearly_savings', 0):,.2f} annually and a total of RM{savings_data.get('total_savings', 0):,.2f} over {savings_data.get('tenure', 0)} years.\n"
        )

        # Additional Professional Advice
        conversation = [
            {
                "role": "system",
                "content": (
                    "You are Finzo AI Assistant, a friendly and professional consultant specializing in refinancing solutions. "
                    "Focus first on presenting the user's potential savings clearly and confidently. Then, explain why refinancing is an opportunity many homeowners overlook. "
                    "Highlight that banks benefit from borrowers continuing to pay higher interest rates, but refinancing empowers users to save more and invest in their future, a holiday getaway or even upgrade of lifestyle. "
                    "Keep the tone approachable, helpful, and reassuring, positioning yourself as a knowledgeable partner in financial improvement. Avoid greetings and closings."
                )
            },
            {
                "role": "user",
                "content": (
                    f"The user could save:\n"
                    f"Monthly: RM{savings_data.get('monthly_savings', 0):,.2f}\n"
                    f"Yearly: RM{savings_data.get('yearly_savings', 0):,.2f}\n"
                    f"Total: RM{savings_data.get('total_savings', 0):,.2f} over {savings_data.get('tenure', 0)} years\n"
                    f"Current Rate: {savings_data.get('current_rate', 0):.2f}%\n"
                    f"New Rate: {savings_data.get('new_rate', 0):.2f}%\n"
                    "Explain how refinancing helps control finances and reduces overpayment."
                )
            }
        ]

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=conversation,
            temperature=0.7
        )

        return savings_message + response.choices[0].message.content.strip()

    except Exception as e:
        logging.error(f"Error generating convincing message: {e}")
        return (
            f"Refinancing could save you approximately RM{savings_data.get('monthly_savings', 0):,.2f} per month, "
            f"RM{savings_data.get('yearly_savings', 0):,.2f} annually, and RM{savings_data.get('total_savings', 0):,.2f} over {savings_data.get('tenure', 0)} years. "
            "Feel free to reach out if you need more information or assistance at https://wa.me/60126181683."
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

        question = "Great! What's your name?"
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
        question = "Could you kindly share your name again?"
        message = {
            "text": f"Please provide a valid name.\n\n_{question}_"
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Invalid name provided.")
        return

    user.name = name
    user.state = STATES['PHONE_COLLECTION']
    db.session.commit()

    question = "May I have your phone number to proceed further?"
    message = {
        "text": f"Nice to meet you, {user.name}! {question}\n\nExample: 0123456789 (exclude country code)"
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Name collected and phone number collection initiated.")

def handle_phone_collection(user: User, messenger_id: str, user_input: str):
    phone = re.sub(r"[^\d+]", "", user_input)
    if not is_valid_phone(phone):
        message = {
            "text": "Please provide a valid Malaysian phone number starting with '01' and containing 10 or 11 digits."
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Invalid phone number provided.")
        return

    user.phone_number = phone
    user.state = STATES['PATH_SELECTION']
    db.session.commit()

    message = {
        "text": (
            "Do you know your outstanding balance, interest rate, and remaining tenure?\n\n"
            "If not, we'll use estimations for the calculation. For the most accurate results, please check this information in your bank app before proceeding."
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
            "Could you share your outstanding loan amount?\n\n"
            "Key in digits, for example: 500k or 500000"
        )
        message = {"text": question}
        send_messenger_message(messenger_id, message)
        logging.debug("Path A selected: Gather outstanding balance.")
    elif user_input == "KNOW_DETAILS_NO":
        user.state = STATES['PATH_B_GATHER_ORIGINAL_AMOUNT']
        db.session.commit()
        question = (
            "Could you let us know the original loan amount?\n\n"
            "Key in digits, for example: 500k or 500000"
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
        question = "Could you provide your outstanding loan amount again?"
        message = {"text": f"Sorry, I couldn't parse that.\n\n{question}"}
        send_messenger_message(messenger_id, message)
        logging.debug("Failed to parse outstanding balance.")
        return

    # Save balance and move to the next step
    user.outstanding_balance = balance
    user.state = STATES['PATH_A_GATHER_INTEREST']
    db.session.commit()

    question = "What is your current interest rate (in %)?"
    message = {"text": question}
    send_messenger_message(messenger_id, message)
    logging.debug("Outstanding balance collected and interest rate collection initiated.")

def handle_path_a_interest(user: User, messenger_id: str, user_input: str):
    try:
        interest = float(user_input.replace("%", "").strip())
    except ValueError:
        question = "What is your current interest rate (in %)?"
        message = {
            "text": f"Sorry, I couldn't parse that.\n\n{question}\n\nExample: 4.5 or 4.75"
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Failed to parse interest rate.")
        return

    user.current_interest_rate = interest
    user.state = STATES['PATH_A_GATHER_TENURE']
    db.session.commit()

    question = "How many years remain on your loan tenure?"
    message = {
        "text": f"{question}\n\nExample: 20 or 25"
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Interest rate collected and remaining tenure collection initiated.")

def handle_path_a_tenure(user: User, messenger_id: str, user_input: str):
    try:
        tenure = float(re.sub(r"[^\d\.]", "", user_input))
    except ValueError:
        question = "Could you provide the remaining tenure (in years) again?"
        message = {
            "text": f"Sorry, I couldn't parse that.\n\n{question}\n\nExample: 10 or 15"
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

    # Retrieve user inputs
    balance = user.outstanding_balance
    interest = user.current_interest_rate
    tenure = user.remaining_tenure

    # Validate inputs
    if balance is None or interest is None or tenure is None:
        send_messenger_message(messenger_id, {"text": "I'm missing data. Type 'restart' or re-enter details."})
        logging.error("Missing data for Path A calculation.")
        return

    # Perform calculations
    new_rate = get_current_bank_rate(balance)
    current_monthly = calculate_monthly_payment(balance, interest, tenure)
    new_monthly = calculate_monthly_payment(balance, new_rate, tenure)

    monthly_savings = current_monthly - new_monthly
    yearly_savings = monthly_savings * 12
    total_savings = monthly_savings * tenure * 12

    # Update user attributes in database
    user.monthly_savings = monthly_savings
    user.yearly_savings = yearly_savings
    user.total_savings = total_savings
    user.tenure = tenure
    user.current_interest_rate = interest
    user.new_rate = new_rate
    db.session.commit()

    # Generate summary message
    summary = (
        f"🏦 Current Loan:\n"
        f"• Monthly Payment: RM{current_monthly:,.2f}\n"
        f"• Interest Rate: {interest:.2f}%\n\n"
        f"💰 After Refinancing:\n"
        f"• New Monthly Payment: RM{new_monthly:,.2f}\n"
        f"• New Interest Rate: {new_rate:.2f}%\n\n"
        f"🎯 Your Savings:\n"
        f"• Monthly: RM{monthly_savings:,.2f}\n"
        f"• Yearly: RM{yearly_savings:,.2f}\n"
        f"• Total: RM{total_savings:,.2f} over {int(tenure)} years\n\n"
    )
    logging.debug("Path A calculation summary prepared.")

    # Generate GPT convincing message
    savings_data = {
        'monthly_savings': monthly_savings,
        'yearly_savings': yearly_savings,
        'total_savings': total_savings,
        'tenure': tenure,
        'current_rate': interest,
        'new_rate': new_rate
    }
    convincing_msg = generate_convincing_message(savings_data)
    logging.debug("GPT convincing message generated.")

    # Combine summary and convincing messages
    combined_message = f"{summary}\n\n{convincing_msg}"

    # Send combined message in chunks
    send_long_message(messenger_id, combined_message)
    logging.debug("Combined summary and convincing message sent.")

    # Notify admin
    notify_admin(user, "Loan Analysis Summary")
    logging.debug("Admin notification sent.")

    # Inquiry mode prompt
    time.sleep(3)
    send_messenger_message(messenger_id, {"text": "You are now talking to Finzo AI. Feel free to ask any questions about refinancing and loans!"})
    logging.debug("Inquiry mode prompt sent.")

    # **State Transition to FAQ Mode**
    user.state = STATES['WAITING_INPUT']  # Transition to FAQ mode
    db.session.commit()
    logging.debug("Transitioned to FAQ mode (WAITING_INPUT).")


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
        "text": "May I know the original loan tenure in years?"
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
        "text": "What is your current monthly payment/installment?"
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
        "text": "How many years have you paid so far?"
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

    try:
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
        user.current_interest_rate = guessed_rate
        user.new_rate = new_rate
        user.outstanding_balance = current_outstanding
        db.session.commit()
        logging.debug("Path B calculation details updated for user.")
    except Exception as e:
        db.session.rollback()  # Roll back changes if any error occurs
        logging.error(f"Error during Path B calculation: {e}")
        send_messenger_message(messenger_id, {"text": "An error occurred. Please try again or contact admin."})
        return

    # Generate summary message
    summary = (
        f"🏦 Current Loan:\n"
        f"• Monthly Payment: RM{current_monthly_calc:,.2f}\n"
        f"• Estimated Interest Rate: {guessed_rate:.2f}%\n\n"
        f"💰 After Refinancing:\n"
        f"• New Monthly Payment: RM{new_monthly_calc:,.2f}\n"
        f"• New Interest Rate: {new_rate:.2f}%\n\n"
        f"🎯 Your Savings:\n"
        f"• Monthly: RM{monthly_savings:,.2f}\n"
        f"• Yearly: RM{yearly_savings:,.2f}\n"
        f"• Total: RM{total_savings:,.2f} over {int(remain_tenure)} years\n\n"
    )
    logging.debug("Path B calculation summary prepared.")

    # Skip GPT processing if savings are low
    if monthly_savings < 50:
        low_savings_message = (
            f"Based on your details, you could save RM{monthly_savings:,.2f} per month. "
            f"For personalized advice, contact our admin directly: [Click Here](https://wa.me/60126181683)"
        )
        send_messenger_message(messenger_id, {"text": low_savings_message})
        logging.debug("Low savings detected. GPT processing skipped.")
    else:
        # Generate GPT convincing message
        savings_data = {
            'monthly_savings': monthly_savings,
            'yearly_savings': yearly_savings,
            'total_savings': total_savings,
            'tenure': remain_tenure,
            'current_rate': guessed_rate,
            'new_rate': new_rate
        }

        try:
            convincing_msg = generate_convincing_message(savings_data)
            logging.debug("GPT convincing message generated.")
        except Exception as e:
            logging.error(f"Error generating GPT convincing message: {e}")
            convincing_msg = "Refinancing could save you a significant amount. Contact us for further assistance."

        # Combine summary and convincing messages
        combined_message = f"{summary}\n\n{convincing_msg}"
        send_long_message(messenger_id, combined_message)
        logging.debug("Combined summary and convincing message sent.")

    # Notify admin with detailed summary
    try:
        admin_summary = (
            f"📊 Loan Analysis Summary\n\n"
            f"👤 Name: {user.name or 'N/A'}\n"
            f"📞 Contact: {user.phone_number or 'N/A'}\n\n"
            f"🏦 Loan Details:\n"
            f"• Monthly Payment: RM{current_monthly_calc:,.2f}\n"
            f"• Estimated Rate: {guessed_rate:.2f}%\n"
            f"• New Monthly Payment: RM{new_monthly_calc:,.2f}\n"
            f"• New Rate: {new_rate:.2f}%\n\n"
            f"💰 Savings:\n"
            f"• Monthly: RM{monthly_savings:,.2f}\n"
            f"• Yearly: RM{yearly_savings:,.2f}\n"
            f"• Total: RM{total_savings:,.2f} over {int(remain_tenure)} years\n\n"
            f"🔗 Admin Contact: [WhatsApp](https://wa.me/60126181683)"
        )
        send_messenger_message(os.getenv("ADMIN_MESSENGER_ID"), {"text": admin_summary})
        logging.debug("Admin notification sent with extended details.")
    except Exception as e:
        logging.error(f"Error sending admin notification: {e}")

    # Inquiry mode prompt
    send_messenger_message(messenger_id, {"text": "You are now talking to Finzo AI. Feel free to ask any questions about refinancing and loans!"})
    logging.debug("Inquiry mode prompt sent.")

    # State transition to FAQ mode
    try:
        user.state = STATES['WAITING_INPUT']
        db.session.commit()
        logging.debug("Transitioned to FAQ mode (WAITING_INPUT).")
    except Exception as e:
        db.session.rollback()
        logging.error(f"State transition failed: {e}")

def handle_waiting_input(user: User, messenger_id: str, user_input: str):
    """
    Handles general user queries after savings calculation.

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
    Handles FAQ queries with admin contact detection and fallback GPT responses.
    """
    logging.debug("Entering handle_faq function.")

    # Debug logs for user state and calculation data
    logging.debug(f"User Data - Name: {user.name}, Phone: {user.phone_number}")
    logging.debug(f"Monthly Savings: RM{user.monthly_savings:,.2f}")
    logging.debug(f"Yearly Savings: RM{user.yearly_savings:,.2f}")
    logging.debug(f"Total Savings: RM{user.total_savings:,.2f}")
    logging.debug(f"Current Interest Rate: {user.current_interest_rate:.2f}%")
    logging.debug(f"New Rate: {user.new_rate:.2f}%")
    logging.debug(f"Remaining Tenure: {user.remaining_tenure} years")

    # Admin contact keywords and phrases
    admin_keywords = [
        'admin', 'agent', 'contact', 'human', 'person', 'representative',
        'staff', 'support', 'help desk', 'helpdesk', 'customer service',
        'speak to someone', 'talk to someone', 'real person', 'live chat',
        'how do i contact admin', 'connect me to admin', 'admin details', 'talk to admin'
    ]

    # Check for admin-related queries (case-insensitive)
    user_input_lower = user_input.lower()
    if any(keyword in user_input_lower for keyword in admin_keywords):
        # Send admin contact details immediately
        admin_message = (
            "📞 You can contact our admin directly via WhatsApp: [Click Here](https://wa.me/60126181683)\n\n"
            "Let us know if you need more assistance!"
        )
        send_messenger_message(messenger_id, {"text": admin_message})
        logging.debug("Admin contact details sent immediately.")

        # No further processing required
        return

    # Process general FAQ queries using GPT if no admin-related keywords matched
    try:
        # Prepare GPT conversation context
        conversation = [
            {
                "role": "system",
                "content": (
                    "You are Finzo AI Buddy, an expert in refinancing and loan advisory. "
                    "Answer the user's question accurately and concisely based on refinancing topics. "
                    "Avoid suggesting external sources and only focus on Finzo-related details."
                )
            },
            {
                "role": "user",
                "content": user_input
            }
        ]

        # GPT request
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=conversation,
            temperature=0.7
        )

        # Extract GPT-generated response
        faq_response = response.choices[0].message.content.strip()
        send_messenger_message(messenger_id, {"text": faq_response})
        logging.debug(f"FAQ response sent: {faq_response}")

    except Exception as e:
        # Log error and provide fallback response
        logging.error(f"Error generating FAQ response with GPT-3.5-turbo: {e}")
        fallback_response = (
            "I'm sorry, I couldn't process your request. "
            "Please contact admin directly at [Click Here](https://wa.me/60126181683) for assistance."
        )
        send_messenger_message(messenger_id, {"text": fallback_response})
        logging.debug("Fallback response sent due to GPT error.")

    # Update user state to allow further questions
    user.state = STATES['WAITING_INPUT']
    db.session.commit()
    logging.debug("User state updated to WAITING_INPUT.")

    # Notify admin about the FAQ query
    notify_admin(user, "FAQ Query Received")
    logging.debug(f"Admin notified about FAQ query: {user_input}")


# Admin Notification Function
def notify_admin(user: User, event_name: str):
    """
    Sends a notification to the admin about a new lead with key details.
    """
    # Get admin Messenger ID from environment variables
    admin_id = os.getenv("ADMIN_MESSENGER_ID")
    if not admin_id or not admin_id.isdigit():
        logging.warning("No valid ADMIN_MESSENGER_ID set. Skipping notify_admin.")
        return

    try:
        # Prepare the admin notification message
        admin_summary = (
            f"📊 {event_name}\n\n"
            f"👤 *Lead Details:*\n"
            f"• Name: {user.name or 'N/A'}\n"
            f"• Contact: {user.phone_number or 'N/A'}\n\n"
            f"🏦 *Loan Details:*\n"
            f"• Remaining Tenure: {user.tenure if user.tenure else 'N/A'} years\n"
            f"• Current Rate: {user.current_interest_rate:.2f}%\n"
            f"• New Rate: {user.new_rate:.2f}%\n\n"
            f"💰 *Savings Summary:*\n"
            f"• Monthly: RM{user.monthly_savings:,.2f}\n"
            f"• Yearly: RM{user.yearly_savings:,.2f}\n"
            f"• Total: RM{user.total_savings:,.2f} over {int(user.tenure) if user.tenure else 'N/A'} years\n\n"
            f"🔗 Admin Contact: [WhatsApp](https://wa.me/60126181683)"
        )

        # Send the message to admin
        send_messenger_message(admin_id, {"text": admin_summary})
        logging.debug(f"Admin notification sent successfully for event: {event_name}")

    except Exception as e:
        # Log the error if any issues occur
        logging.error(f"Error in notify_admin: {e}")


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
            "• I’m here to help you explore refinancing options.\n"
            "• We’ll work together to optimize your housing loans.\n"
            "• My goal is to help you identify potential savings* and *improve financial efficiency*.\n\n"
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

# Update State Handlers
STATE_HANDLERS = {
    STATES['GET_STARTED_YES']: handle_get_started_yes,
    STATES['CONTACT_ADMIN']: handle_contact_admin,
    STATES['NAME_COLLECTION']: handle_name_collection,
    STATES['PHONE_COLLECTION']: handle_phone_collection,
    STATES['PATH_SELECTION']: handle_path_selection,
    STATES['PATH_A_GATHER_BALANCE']: handle_path_a_balance,
    STATES['PATH_A_GATHER_INTEREST']: handle_path_a_interest,
    STATES['PATH_A_GATHER_TENURE']: handle_path_a_tenure,
    STATES['PATH_A_CALCULATE']: handle_path_a_calculate,
    STATES['PATH_B_GATHER_ORIGINAL_AMOUNT']: handle_path_b_original_amount,
    STATES['PATH_B_GATHER_ORIGINAL_TENURE']: handle_path_b_original_tenure,
    STATES['PATH_B_GATHER_MONTHLY_PAYMENT']: handle_path_b_monthly_payment,
    STATES['PATH_B_GATHER_YEARS_PAID']: handle_path_b_years_paid,
    STATES['PATH_B_CALCULATE']: handle_path_b_calculate,
    STATES['WAITING_INPUT']: handle_waiting_input,
    STATES['FAQ']: handle_faq,
    STATES['END']: handle_unhandled_state
}

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

            # Check if it's a message event or postback event
            if 'message' in event:
                message = event['message']
                # Check if the message contains a quick_reply
                if 'quick_reply' in message:
                    user_input = message['quick_reply']['payload']
                    logging.debug(f"Received quick_reply payload: {user_input}")
                else:
                    user_input = message.get('text', '').strip()
                    logging.debug(f"Received text: {user_input}")
            elif 'postback' in event:
                postback = event['postback']
                user_input = postback.get('payload', '').strip()
                logging.debug(f"Received postback payload: {user_input}")

            if not sender_id or not sender_id.isdigit():
                logging.error("Invalid messenger ID.")
                continue  # Skip to the next event

            # Check if user exists in the database
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

            # Check if the user has been idle for more than 24 hours
            last_interaction = user.last_interaction
            if last_interaction:
                time_diff = datetime.utcnow() - last_interaction
                if time_diff > timedelta(hours=24):
                    # Send welcome back message if idle for more than 24 hours
                    send_welcome_back_message(sender_id)
                    logging.debug("User was idle for more than 24 hours. Sent welcome back message.")
            
            # Handle 'restart' command at any time
            if user_input.lower() == 'restart':
                reset_user(user)
                send_initial_message(sender_id)
                logging.debug("User initiated restart. State reset and initial message sent.")
                continue  # Move to the next event

            # Handle other specific payloads like "CONTACT_ADMIN" or "GET_STARTED_YES"
            if user_input == "CONTACT_ADMIN":
                handle_contact_admin(user, sender_id, user_input)
                continue

            if user_input == "GET_STARTED_YES":
                handle_get_started_yes(user, sender_id, user_input)
                continue

            # Main Logic Flow
            if not user.state:
                user.state = STATES['GET_STARTED_YES']
                db.session.commit()
                logging.debug("User state was None. Set to GET_STARTED_YES.")
            
            # Call the appropriate state handler
            state_handler = STATE_HANDLERS.get(user.state, handle_unhandled_state)
            state_handler(user, sender_id, user_input)

            # Update last interaction timestamp
            user.last_interaction = datetime.utcnow()
            db.session.commit()

        return jsonify({"status": "success"}), 200

    except Exception as e:
        logging.error(f"Error in process_message: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

def send_long_message(messenger_id, text):
    """
    Splits long messages into chunks and sends them sequentially.
    Facebook Messenger API supports only up to 2000 characters per message.
    """
    MAX_LENGTH = 2000  # Facebook's message limit
    chunks = [text[i:i+MAX_LENGTH] for i in range(0, len(text), MAX_LENGTH)]

    for chunk in chunks:
        send_messenger_message(messenger_id, {"text": chunk})
        time.sleep(1)  # Small delay to avoid hitting rate limits
    
def check_user_idle(user):
    # Assume user.last_interaction is a datetime field in the User model
    if user.last_interaction:
        now = datetime.utcnow()
        time_difference = now - user.last_interaction
        if time_difference > timedelta(days=1):  # If the user is idle for more than 24 hours
            return True
    return False

def send_welcome_back_message(messenger_id):
    message = {
        "text": (
            "Hi, welcome back! 👋\n\n"
            "If you need to calculate again, please type 'restart'."
        )
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Sent 'Welcome back' message to user.")

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
    user.monthly_savings = None
    user.yearly_savings = None
    user.total_savings = None
    user.tenure = None
    user.new_rate = None
    db.session.commit()
    logging.debug("User data reset to initial state with default language set to English.")

