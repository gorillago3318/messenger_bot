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
from datetime import timedelta


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

    # Fetch the appropriate message based on the user's language
    language = user.language  # This should be 'en', 'ms', or 'zh' based on user input

    # Load the corresponding language file (assuming en.json, ms.json, zh.json are stored properly)
    try:
        with open(f'backend/routes/languages/{language}.json', 'r', encoding='utf-8') as f:
            lang_data = json.load(f)
    except FileNotFoundError:
        logging.error(f"Language file for {language} not found, falling back to English.")
        with open('backend/routes/languages/en.json', 'r', encoding='utf-8') as f:
            lang_data = json.load(f)
    
    # Use the language data to construct the message
    message = {
        "text": lang_data.get("contact_admin_message", "You can contact our admin directly at:\n\n"
                                                     "📞 WhatsApp: [Click here to chat](https://wa.me/60126181683)\n\n"
                                                     "Let us know if you need any further assistance!")
    }

    # Send the message to the user
    send_messenger_message(messenger_id, message)
    logging.debug("Admin contact details sent to user.")

    # Update state to WAITING_INPUT for follow-up inquiries
    user.state = STATES['WAITING_INPUT']
    db.session.commit()


STATES = {
    'LANGUAGE_SELECTION': 'LANGUAGE_SELECTION',  # Add this line
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

def is_valid_phone(phone: str, language: str) -> bool:
    """
    Validates Malaysian phone numbers:
    - Starts with '01'
    - Contains only digits
    - Is 10 or 11 digits long
    """
    if not re.fullmatch(r"01\d{8,9}", phone):
        # Return different error messages based on the user's language
        if language == 'ms':
            return "Sila masukkan nombor telefon yang sah bermula dengan '01' dan mempunyai 10 atau 11 digit."
        elif language == 'zh':
            return "请输入有效的马来西亚电话号码，以'01'开头，并包含10或11位数字。"
        else:
            return "Please provide a valid Malaysian phone number starting with '01' and containing 10 or 11 digits."
    return True


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

def get_current_bank_rate(loan_size: float, language: str) -> float:
    """
    Retrieves the current bank rate based on loan size from the BankRate table.
    Falls back to 3.8% if no matching rate is found.
    """
    try:
        # Check if loan_size is valid
        if loan_size is None or loan_size <= 0:
            # Language-specific fallback error message
            if language == 'ms':
                logging.error("Saiz pinjaman adalah tidak sah atau tiada. Menggunakan kadar faedah default 3.8%.")
            elif language == 'zh':
                logging.error("贷款金额无效或未提供。使用默认的3.8%的利率。")
            else:
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
        # Error handling with language-specific logging
        if language == 'ms':
            logging.error(f"Masalah teknikal semasa mendapatkan kadar bank: {e}")
        elif language == 'zh':
            logging.error(f"获取银行利率时出错: {e}")
        else:
            logging.error(f"Error fetching bank rate: {e}")
        return 3.8  # Fallback rate

def send_initial_message(messenger_id, language='en'):
    # Language-specific welcome message
    if language == 'ms':
        message_text = (
            "👋 Selamat datang ke Pembantu AI Finzo!\n\n"
            "• Saya di sini untuk membantu anda menjelajah pilihan pembiayaan semula.\n"
            "• Kita akan bekerjasama untuk mengoptimumkan pinjaman perumahan anda.\n"
            "• Matlamat saya adalah untuk membantu anda mengenal pasti potensi penjimatan dan meningkatkan kecekapan kewangan.\n\n"
            "Adakah anda bersedia untuk bermula?"
        )
        quick_replies = [
            {"content_type": "text", "title": "Ya, mari mula!", "payload": "GET_STARTED_YES"},
            {"content_type": "text", "title": "Bahasa Malaysia", "payload": "LANG_MS"},
            {"content_type": "text", "title": "Chinese", "payload": "LANG_ZH"},
        ]
    elif language == 'zh':
        message_text = (
            "👋 欢迎来到Finzo AI助手！\n\n"
            "• 我在这里帮助您探索再融资选项。\n"
            "• 我们将共同努力优化您的住房贷款。\n"
            "• 我的目标是帮助您识别潜在节省并提高财务效率。\n\n"
            "准备好开始了吗？"
        )
        quick_replies = [
            {"content_type": "text", "title": "是的，开始吧！", "payload": "GET_STARTED_YES"},
            {"content_type": "text", "title": "马来语", "payload": "LANG_MS"},
            {"content_type": "text", "title": "中文", "payload": "LANG_ZH"},
        ]
    else:  # Default is English
        message_text = (
            "👋 Welcome to Finzo AI Assistant!\n\n"
            "• I’m here to help you explore refinancing options.\n"
            "• We’ll work together to optimize your housing loans.\n"
            "• My goal is to help you identify potential savings and improve financial efficiency.\n\n"
            "Are you ready to get started?"
        )
        quick_replies = [
            {"content_type": "text", "title": "Yes, let's start!", "payload": "GET_STARTED_YES"},
            {"content_type": "text", "title": "Bahasa Malaysia", "payload": "LANG_MS"},
            {"content_type": "text", "title": "Chinese", "payload": "LANG_ZH"},
        ]

    # Construct message with quick replies
    message = {
        "text": message_text,
        "quick_replies": quick_replies
    }

    send_messenger_message(messenger_id, message)
    logging.debug("Initial welcome message sent.")


def handle_language_selection(user: User, messenger_id: str, user_input: str):
    """
    Handles the language selection and proceeds to collect the user's name.
    """
    logging.debug(f"User selected language: {user_input}.")

    # Language mapping
    language_map = {
        'LANG_EN': 'en',
        'LANG_MS': 'ms',
        'LANG_ZH': 'zh'
    }

    # Update user's language preference
    if user_input in language_map:
        user.language = language_map[user_input]
        db.session.commit()

        # Move the user to the NAME_COLLECTION state
        user.state = STATES['NAME_COLLECTION']
        db.session.commit()

        # Ask for the user's name based on the selected language
        if user.language == 'ms':
            message = {"text": "Hebat! Bolehkah kami mendapatkan nama anda?"}
        elif user.language == 'zh':
            message = {"text": "太好了！请问您的名字是什么？"}
        else:
            message = {"text": "Great! Can we please get your name?"}

        send_messenger_message(messenger_id, message)
        logging.debug("Prompted user to provide name based on selected language.")

    else:
        # If an invalid language option is chosen
        message = {"text": "Please select a valid language by clicking one of the options."}
        send_messenger_message(messenger_id, message)
        logging.debug("Invalid language selection.")


def generate_convincing_message(savings_data: dict, language: str) -> str:
    """
    Uses GPT-4 to generate a personalized convincing message based on savings calculations.
    This function now supports multiple languages: English (en), Bahasa Malaysia (ms), Chinese (zh).
    """
    try:
        # Select language-specific messages
        if language == 'ms':
            low_savings_msg = (
                "Berdasarkan maklumat anda, anggaran penjimatan dari pembiayaan semula adalah kurang daripada RM10,000. "
                "Memandangkan pembiayaan semula melibatkan bayaran guaman dan duti setem, ia mungkin tidak berbaloi pada masa ini. "
                "Namun, kami sedia membantu sekiranya anda mempunyai sebarang pertanyaan atau memerlukan panduan lanjut. Sila hubungi kami di https://wa.me/60126181683."
            )
            zero_savings_msg = (
                "Berdasarkan maklumat anda, nampaknya pinjaman anda sudah dioptimumkan dengan baik, dan pembiayaan semula mungkin tidak memberikan penjimatan yang signifikan. "
                "Namun, kami di sini untuk membantu dengan sebarang pertanyaan atau keperluan pembiayaan semula pada masa hadapan. Perkhidmatan kami adalah percuma, dan anda boleh sentiasa menghubungi kami di https://wa.me/60126181683 jika memerlukan maklumat atau bantuan lanjut!"
            )
            savings_msg = (
                f"Penjimatan Bulanan: RM{savings_data.get('monthly_savings', 0):,.2f}\n"
                f"Penjimatan Tahunan: RM{savings_data.get('yearly_savings', 0):,.2f}\n"
                f"Jumlah Penjimatan: RM{savings_data.get('total_savings', 0):,.2f} sepanjang {savings_data.get('tenure', 0)} tahun\n"
                f"Kadar Faedah Semasa: {savings_data.get('current_rate', 0):.2f}%\n"
                f"Kadar Faedah Baru: {savings_data.get('new_rate', 0):.2f}%\n"
            )
        elif language == 'zh':
            low_savings_msg = (
                "根据您的信息，预计通过再融资的节省低于RM10,000。 "
                "考虑到再融资会涉及法律费用和印花税，现在可能不值得麻烦。 "
                "但是，如果您有任何问题或需要进一步的指导，我们很乐意提供帮助。请随时通过 https://wa.me/60126181683 与我们联系。"
            )
            zero_savings_msg = (
                "根据您的信息，看起来您的当前贷款已经优化得很好，再融资可能不会带来显著的节省。 "
                "然而，我们随时准备为您提供任何问题的帮助或未来的再融资需求。我们的服务是免费的，如果您想了解更多信息或需要帮助，可以随时联系我们 https://wa.me/60126181683！"
            )
            savings_msg = (
                f"每月节省: RM{savings_data.get('monthly_savings', 0):,.2f}\n"
                f"每年节省: RM{savings_data.get('yearly_savings', 0):,.2f}\n"
                f"总节省: RM{savings_data.get('total_savings', 0):,.2f} 经过 {savings_data.get('tenure', 0)} 年\n"
                f"当前利率: {savings_data.get('current_rate', 0):.2f}%\n"
                f"新利率: {savings_data.get('new_rate', 0):.2f}%\n"
            )
        else:  # Default to English
            low_savings_msg = (
                "Based on your details, the estimated savings from refinancing are below RM10,000. "
                "Considering that refinancing incurs legal fees and stamp duty, it may not be worth the hassle right now. "
                "However, we’re happy to assist if you have any questions or need further guidance. Feel free to reach out at https://wa.me/60126181683."
            )
            zero_savings_msg = (
                "Based on your details, it looks like your current loan is already well-optimized, and refinancing may not result in significant savings. "
                "However, we are here to assist you with any questions or future refinancing needs. Our service is free, and you can always reach out to us at https://wa.me/60126181683 if you'd like more information or need assistance!"
            )
            savings_msg = (
                f"Monthly Savings: RM{savings_data.get('monthly_savings', 0):,.2f}\n"
                f"Yearly Savings: RM{savings_data.get('yearly_savings', 0):,.2f}\n"
                f"Total Savings: RM{savings_data.get('total_savings', 0):,.2f} over {savings_data.get('tenure', 0)} years\n"
                f"Current Interest Rate: {savings_data.get('current_rate', 0):.2f}%\n"
                f"New Interest Rate: {savings_data.get('new_rate', 0):.2f}%\n"
            )

        # Check if savings are below 10k
        if savings_data['total_savings'] < 10000:
            return low_savings_msg

        # Check if savings are zero or negative
        if savings_data['monthly_savings'] <= 0:
            return zero_savings_msg

        # If the savings are good, use GPT-4 to generate a more personalized message
        conversation = [
            {
                "role": "system",
                "content": (
                    "You are Finzo AI Assistant, an expert in refinancing solutions. Highlight potential savings from refinancing and explain that many homeowners overpay simply due to lack of information about better options. "
                    "Emphasize that this service is completely free, with no hidden fees, and an agent is available to assist unless the user opts out. "
                    "Encourage users to take control of their finances and avoid overpaying unnecessarily, while keeping a professional, friendly, and reassuring tone. "
                    "message especially digit will have to clearly stated with commas for thousands and millions."
                    "Reply with the admin WhatsApp contact link at wa.me/60126181683 whenever the user asks for admin, agent, company, or human contact."
                )
            },
            {
                "role": "user",
                "content": savings_msg + (
                    "Frame the message to emphasize how refinancing helps regain financial control and reduce costs. "
                    "Mention that continuing with the current loan benefits the banks, and exploring refinancing options provides the user with better opportunities. "
                    "Encourage questions and emphasize that an agent will assist with more details, maintaining a professional and informative tone."
                )
            }
        ]

        # Use GPT-4 to generate a convincing message
        response = openai.ChatCompletion.create(
            model="gpt-4",  # Using GPT-4 for convincing message
            messages=conversation,
            temperature=0.7
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        logging.error(f"Error generating convincing message: {e}")
        return (
            f"You may be overpaying on your home loan. Refinancing at {savings_data.get('new_rate', 0):.2f}% could save you "
            f"RM{savings_data.get('monthly_savings', 0):,.2f} monthly and RM{savings_data.get('total_savings', 0):,.2f} over {savings_data.get('tenure', 0)} years. "
            "Our service is completely free, and our agents are here to assist—unless you say 'no,' we'll be in touch to help you explore your savings. Feel free to ask any follow-up questions!"
        )


def generate_faq_response_with_gpt(user_input: str) -> str:
    """
    Uses GPT-3.5 to generate a response for an unmatched FAQ.
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
            model="gpt-3.5-turbo",  # Using GPT-3.5 for FAQ response
            messages=conversation,
            temperature=0.7
        )
        gpt_response = response.choices[0].message.content.strip()
        return gpt_response

    except Exception as e:
        logging.error(f"Error generating FAQ response with GPT: {e}")
        return "I'm sorry, I don't have an answer to that. You can ask anything regarding refinancing and housing loans."


def handle_name_collection(user: User, messenger_id: str, user_input: str):
    name = user_input.strip()
    if not is_valid_name(name):
        question = get_message(user.language, "name_invalid")  # Fetching language-specific message
        message = {
            "text": f"{get_message(user.language, 'please_provide_valid_name')} {question}"
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Invalid name provided.")
        return

    user.name = name
    user.state = STATES['PHONE_COLLECTION']
    db.session.commit()

    question = get_message(user.language, "phone_number_question")  # Fetching language-specific message
    message = {
        "text": f"{get_message(user.language, 'nice_to_meet_you')} {user.name}! {question}\n\n{get_message(user.language, 'phone_number_example')}"
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Name collected and phone number collection initiated.")

def handle_phone_collection(user: User, messenger_id: str, user_input: str):
    phone = re.sub(r"[^\d+]", "", user_input)
    if not is_valid_phone(phone):
        message = {
            "text": get_message(user.language, "invalid_phone_number")
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Invalid phone number provided.")
        return

    user.phone_number = phone
    user.state = STATES['PATH_SELECTION']
    db.session.commit()

    message = {
        "text": (
            f"{get_message(user.language, 'do_you_know_balance')} {get_message(user.language, 'check_bank_app_before_proceeding')}"
        ),
        "quick_replies": [
            {
                "content_type": "text",
                "title": get_message(user.language, "yes"),
                "payload": "KNOW_DETAILS_YES"
            },
            {
                "content_type": "text",
                "title": get_message(user.language, "no"),
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

        question = get_message(user.language, "outstanding_loan_amount_question")  # Fetching language-specific message
        message = {"text": question}
        send_messenger_message(messenger_id, message)
        logging.debug("Path A selected: Gather outstanding balance.")

    elif user_input == "KNOW_DETAILS_NO":
        user.state = STATES['PATH_B_GATHER_ORIGINAL_AMOUNT']
        db.session.commit()

        question = get_message(user.language, "original_loan_amount_question")  # Fetching language-specific message
        message = {"text": question}
        send_messenger_message(messenger_id, message)
        logging.debug("Path B selected: Gather original loan amount.")

    else:
        # Invalid input handling
        message = {"text": get_message(user.language, "invalid_path_selection")}
        send_messenger_message(messenger_id, message)
        logging.debug("Invalid path selection input.")

# Path A Handlers
def handle_path_a_balance(user: User, messenger_id: str, user_input: str):
    try:
        balance = parse_number_with_suffix(user_input)
    except ValueError:
        question = get_message(user.language, "outstanding_loan_amount_again")  # Fetching language-specific message
        message = {"text": f"Sorry, I couldn't parse that.\n\n{question}"}
        send_messenger_message(messenger_id, message)
        logging.debug("Failed to parse outstanding balance.")
        return

    # Save balance and move to the next step
    user.outstanding_balance = balance
    user.state = STATES['PATH_A_GATHER_INTEREST']
    db.session.commit()

    question = get_message(user.language, "current_interest_rate_question")  # Fetching language-specific message
    message = {"text": question}
    send_messenger_message(messenger_id, message)
    logging.debug("Outstanding balance collected and interest rate collection initiated.")


def handle_path_a_interest(user: User, messenger_id: str, user_input: str):
    try:
        interest = float(user_input.replace("%", "").strip())
    except ValueError:
        question = get_message(user.language, "current_interest_rate_question")  # Fetching language-specific message
        message = {
            "text": f"Sorry, I couldn't parse that.\n\n{question}\n\n{get_message(user.language, 'example_interest_rate')}"
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Failed to parse interest rate.")
        return

    user.current_interest_rate = interest
    user.state = STATES['PATH_A_GATHER_TENURE']
    db.session.commit()

    question = get_message(user.language, "remaining_loan_tenure_question")  # Fetching language-specific message
    message = {
        "text": f"{question}\n\n{get_message(user.language, 'example_years_remaining')}"
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Interest rate collected and remaining tenure collection initiated.")

def handle_path_a_tenure(user: User, messenger_id: str, user_input: str):
    try:
        tenure = float(re.sub(r"[^\d\.]", "", user_input))
    except ValueError:
        question = get_message(user.language, "remaining_tenure_question")  # Fetching language-specific message
        message = {
            "text": f"Sorry, I couldn't parse that.\n\n{question}\n\n{get_message(user.language, 'example_years_remaining')}"
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
        message = get_message(user.language, "missing_data_error")  # Dynamic message fetching
        send_messenger_message(messenger_id, {"text": message})
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

    # Send calculation summary in the selected language
    summary = (
        f"🏦 {get_message(user.language, 'current_loan')}:\n"
        f"• {get_message(user.language, 'monthly_payment')}: RM{current_monthly:,.2f}\n"
        f"• {get_message(user.language, 'interest_rate')}: {interest:.2f}%\n\n"
        f"💰 {get_message(user.language, 'after_refinancing')}:\n"
        f"• {get_message(user.language, 'new_monthly_payment')}: RM{new_monthly:,.2f}\n"
        f"• {get_message(user.language, 'new_interest_rate')}: {new_rate:.2f}%\n\n"
        f"🎯 {get_message(user.language, 'your_savings')}:\n"
        f"• {get_message(user.language, 'monthly_savings')}: RM{monthly_savings:,.2f}\n"
        f"• {get_message(user.language, 'yearly_savings')}: RM{yearly_savings:,.2f}\n"
        f"• {get_message(user.language, 'total_savings')}: RM{total_savings:,.2f} {get_message(user.language, 'over_years')} {int(tenure)} {get_message(user.language, 'years')}\n\n"
        f"{get_message(user.language, 'finzo_ai_message')}"
    )

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
            "text": get_message(user.language, "original_loan_amount_error")  # Dynamic message fetching
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Failed to parse original loan amount.")
        return

    user.original_amount = amt
    user.state = STATES['PATH_B_GATHER_ORIGINAL_TENURE']
    db.session.commit()

    message = {
        "text": get_message(user.language, "original_loan_tenure_prompt")  # Dynamic message fetching
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Original loan amount collected and original tenure collection initiated.")

def handle_path_b_original_tenure(user: User, messenger_id: str, user_input: str):
    try:
        tenure = parse_number_with_suffix(user_input)
    except ValueError:
        message = {
            "text": get_message(user.language, "original_tenure_error")  # Dynamic message fetching
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Failed to parse original loan tenure.")
        return

    user.original_tenure = tenure
    user.state = STATES['PATH_B_GATHER_MONTHLY_PAYMENT']
    db.session.commit()

    message = {
        "text": get_message(user.language, "current_monthly_payment_prompt")  # Dynamic message fetching
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Original loan tenure collected and monthly payment collection initiated.")

def handle_path_b_monthly_payment(user: User, messenger_id: str, user_input: str):
    try:
        monthly = parse_number_with_suffix(user_input)
    except ValueError:
        message = {
            "text": get_message(user.language, "monthly_payment_error")  # Dynamic message fetching
        }
        send_messenger_message(messenger_id, message)
        logging.debug("Failed to parse current monthly payment.")
        return

    user.current_monthly_payment = monthly
    user.state = STATES['PATH_B_GATHER_YEARS_PAID']
    db.session.commit()

    message = {
        "text": get_message(user.language, "years_paid_prompt")  # Dynamic message fetching
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Current monthly payment collected and years paid collection initiated.")

def handle_path_b_years_paid(user: User, messenger_id: str, user_input: str):
    try:
        yrs = parse_number_with_suffix(user_input)
    except ValueError:
        message = {
            "text": get_message(user.language, "years_paid_error")  # Fetch dynamic message
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
        message = {
            "text": get_message(user.language, "missing_data_error")  # Fetch dynamic message
        }
        send_messenger_message(messenger_id, message)
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

    # Send the convincing message
    send_messenger_message(messenger_id, {"text": convincing_msg})
    logging.debug("Convincing message sent.")

    # Prepare the Cash-Out Prompt with quick replies (use dynamic language)
    cashout_message = get_message(user.language, "cashout_prompt")  # Fetch dynamic message

    quick_replies = [
        {"content_type": "text", "title": get_message(user.language, "yes_more"), "payload": "CASHOUT_YES"},
        {"content_type": "text", "title": get_message(user.language, "no_thanks"), "payload": "CASHOUT_NO"}
    ]

    # Send the cash-out prompt with quick replies
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
            "text": get_message(user.language, "cashout_offer_prompt"),
            "quick_replies": [
                {
                    "content_type": "text",
                    "title": get_message(user.language, "yes_more"),
                    "payload": "CASHOUT_YES"
                },
                {
                    "content_type": "text",
                    "title": get_message(user.language, "no_thanks"),
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
        question = get_message(user.language, "cashout_amount_question")
        send_messenger_message(messenger_id, {"text": question})
        logging.debug("User accepted cash-out offer. Cash-out amount collection initiated.")
    elif user_input == "CASHOUT_NO":
        # Transition to WAITING_INPUT without cash-out
        user.temp_cashout_amount = 0  # No cash-out
        user.state = STATES['WAITING_INPUT']
        db.session.commit()

        # Notify admin about declined cash-out offer
        admin_summary = (
            f"📊 {get_message(user.language, 'user_declined_cashout')}\n"
            f"Customer: {user.name or get_message(user.language, 'no_name')}\n"
            f"Contact: {user.phone_number or get_message(user.language, 'no_phone')}\n\n"
            f"📊 {get_message(user.language, 'loan_details')}:\n"
            f"• {get_message(user.language, 'outstanding_balance')}: RM{user.outstanding_balance or 0:,.2f}\n"
            f"• {get_message(user.language, 'interest_rate')}: {user.current_interest_rate or 0:.2f}%\n"
            f"• {get_message(user.language, 'remaining_tenure')}: {user.remaining_tenure or 0:.1f} years\n\n"
            f"{get_message(user.language, 'after_refinancing')}:\n"
            f"• {get_message(user.language, 'new_interest_rate')}: {user.new_rate or 0:.2f}%\n"
            f"• {get_message(user.language, 'monthly_savings')}: RM{user.monthly_savings or 0:.2f}\n"
            f"• {get_message(user.language, 'yearly_savings')}: RM{user.yearly_savings or 0:.2f}\n"
            f"• {get_message(user.language, 'total_savings')}: RM{user.total_savings or 0:.2f}\n"
            f"• {get_message(user.language, 'tenure')}: {user.tenure or 0:.1f} years\n\n"
            f"📊 {get_message(user.language, 'cash_out_calculation')}:\n"
            f"• {get_message(user.language, 'main_loan')}: RM{user.outstanding_balance or 0:,.2f} @ {user.new_rate or 0:.2f}% for {int(user.remaining_tenure or 0)} yrs => RM{calculate_monthly_payment(user.outstanding_balance or 0, user.new_rate or 0, user.remaining_tenure or 0):,.2f}/month\n"
            f"• {get_message(user.language, 'cash_out')}: RM{user.temp_cashout_amount or 0:,.2f} @ {user.new_rate or 0:.2f}% for 10 yrs => RM{calculate_monthly_payment(user.temp_cashout_amount or 0, user.new_rate or 0, 10):,.2f}/month\n\n"
            f"💳 {get_message(user.language, 'total_monthly_payment')}: RM{(calculate_monthly_payment(user.outstanding_balance or 0, user.new_rate or 0, user.remaining_tenure or 0) + calculate_monthly_payment(user.temp_cashout_amount or 0, user.new_rate or 0, 10)) or 0:,.2f}\n\n"
            f"Status: {'Accepted Cash-Out Offer' if (user.temp_cashout_amount or 0) > 0 else get_message(user.language, 'declined_cash_out_offer')}"
        )
        notify_admin(user, get_message(user.language, "user_declined_cashout"), admin_summary)
        logging.debug("User declined cash-out offer and admin notified.")

        # FAQ Prompt
        faq_prompt = get_message(user.language, "faq_prompt")
        send_messenger_message(messenger_id, {"text": faq_prompt})
        logging.debug("FAQ prompt sent after declining cash-out offer.")
    else:
        # Handle unexpected inputs
        send_messenger_message(messenger_id, {"text": get_message(user.language, "unexpected_input")})
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
            {"text": get_message(user.language, "cashout_error_message")}
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

    # --- Message for USER --- (using dynamic language support)
    user_summary = (
        f"📊 {get_message(user.language, 'cashout_calculation')}:\n"
        f"• {get_message(user.language, 'main_loan')}: RM{outstanding_balance:,.2f} @ {main_rate:.2f}% for {segment1_tenure} yrs => RM{monthly1:,.2f}/month\n"
        f"• {get_message(user.language, 'cash_out')}: RM{cashout_amount:,.2f} @ {main_rate:.2f}% for 10 yrs => RM{monthly2:,.2f}/month\n\n"
        f"💳 {get_message(user.language, 'total_monthly_payment')}: RM{new_total_monthly:,.2f}\n\n"
        f"{get_message(user.language, 'note')} {get_message(user.language, 'estimated_repayment')}"
    )
    # **Correction:** Remove the nested "message" key
    send_messenger_message(messenger_id, {"text": user_summary})
    logging.debug("Cash-out calculation summary sent to user.")

    # Transition to WAITING_INPUT instead of FAQ
    user.state = STATES['WAITING_INPUT']
    db.session.commit()

    # FAQ Prompt
    faq_prompt = get_message(user.language, "faq_prompt_after_calculation")
    send_messenger_message(messenger_id, {"text": faq_prompt})
    logging.debug("FAQ prompt sent after cash-out calculation.")

    # Send admin notification
    admin_summary = (
        f"📊 {get_message(user.language, 'loan_and_cashout_details')}:\n"
        f"• {get_message(user.language, 'customer')}: {user.name}\n"
        f"• {get_message(user.language, 'contact')}: {user.phone_number}\n\n"
        f"{get_message(user.language, 'current_loan')}:\n"
        f"• {get_message(user.language, 'outstanding_balance')}: RM{user.outstanding_balance:,.2f}\n"
        f"• {get_message(user.language, 'interest_rate')}: {user.current_interest_rate:.2f}%\n"
        f"• {get_message(user.language, 'remaining_tenure')}: {user.remaining_tenure:.1f} years\n\n"
        f"{get_message(user.language, 'after_refinancing')}:\n"
        f"• {get_message(user.language, 'new_interest_rate')}: {user.new_rate:.2f}%\n"
        f"• {get_message(user.language, 'monthly_savings')}: RM{user.monthly_savings:.2f}\n"
        f"• {get_message(user.language, 'yearly_savings')}: RM{user.yearly_savings:.2f}\n"
        f"• {get_message(user.language, 'total_savings')}: RM{user.total_savings:.2f}\n"
        f"• {get_message(user.language, 'tenure')}: {user.tenure:.1f} years\n\n"
        f"📊 {get_message(user.language, 'cash_out_calculation')}:\n"
        f"• {get_message(user.language, 'main_loan')}: RM{outstanding_balance:,.2f} @ {main_rate:.2f}% for {segment1_tenure} yrs => RM{monthly1:,.2f}/month\n"
        f"• {get_message(user.language, 'cash_out')}: RM{cashout_amount:,.2f} @ {main_rate:.2f}% for 10 yrs => RM{monthly2:,.2f}/month\n\n"
        f"💳 {get_message(user.language, 'total_monthly_payment')}: RM{new_total_monthly:,.2f}\n\n"
        f"Status: {'Accepted Cash-Out Offer' if cashout_amount > 0 else get_message(user.language, 'declined_cash_out_offer')}"
    )
    notify_admin(user, get_message(user.language, "user_completed_cashout"), admin_summary)
    logging.debug("Admin notified about completed cash-out refinance calculation.")

def handle_waiting_input(user: User, messenger_id: str, user_input: str):
    """
    Handles general user queries after cash-out calculation using GPT-3.5-turbo.
    """
    logging.debug("Entering handle_waiting_input function.")

    # Prepare context with safe formatting and dynamic language support
    context = (
        f"{get_message(user.language, 'previous_summary')}:\n"
        f"{get_message(user.language, 'monthly_savings')}: RM{user.monthly_savings or 0:,.2f}\n"
        f"{get_message(user.language, 'yearly_savings')}: RM{user.yearly_savings or 0:,.2f}\n"
        f"{get_message(user.language, 'total_savings')}: RM{user.total_savings or 0:,.2f}\n"
        f"{get_message(user.language, 'interest_rate')}: {user.current_interest_rate or 0:.2f}% -> {user.new_rate or 0:.2f}%\n"
        f"{get_message(user.language, 'remaining_tenure')}: {user.remaining_tenure or user.tenure or 0} {get_message(user.language, 'years')}\n"
    )

    try:
        conversation = [
            {
                "role": "system",
                "content": (
                    f"{get_message(user.language, 'system_message')}\n{context}"
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
        send_messenger_message(messenger_id, {"text": reply})
        logging.debug("User question processed and response sent.")

    except Exception as e:
        logging.error(f"Error processing user question: {e}")
        send_messenger_message(
            messenger_id,
            {"text": get_message(user.language, 'error_message')}
        )
        logging.debug("Error occurred while processing user question. Informed user.")

    # Remain in the same state to allow further questions
    user.state = STATES['WAITING_INPUT']
    db.session.commit()
    logging.debug("User state remains at WAITING_INPUT.")

def handle_faq(user: User, messenger_id: str, user_input: str):
    """
    Handles FAQ queries and admin contact requests with GPT-4 for admin messages and GPT-3.5 for FAQs.
    """
    logging.debug("Entering handle_faq function.")

    # Check if user is requesting admin contact
    admin_keywords = [
        'admin', 'agent', 'contact', 'human', 'person', 'representative',
        'staff', 'support', 'help desk', 'helpdesk', 'customer service',
        'speak to someone', 'talk to someone', 'real person', 'live chat'
    ]

    if any(keyword in user_input.lower() for keyword in admin_keywords):
        admin_response = {
            "text": get_message(user.language, "admin_contact_message")
        }
        send_messenger_message(messenger_id, admin_response)
        logging.debug("User requested admin contact - WhatsApp link sent.")
        return

    # If it's not admin request, proceed with FAQ handling via GPT-3.5
    faq_response = generate_faq_response_with_gpt(user_input)
    send_messenger_message(messenger_id, {"text": faq_response})
    logging.debug("FAQ response sent to user.")

    # Load context with enhanced formatting
    context = (
        f"{get_message(user.language, 'previous_summary')}:\n"
        f"{get_message(user.language, 'monthly_savings')}: RM{user.monthly_savings or 0:,.2f}\n"
        f"{get_message(user.language, 'yearly_savings')}: RM{user.yearly_savings or 0:,.2f}\n"
        f"{get_message(user.language, 'total_savings')}: RM{user.total_savings or 0:,.2f}\n"
        f"{get_message(user.language, 'interest_rate')}: {user.current_interest_rate or 0:.2f}% -> {user.new_rate or 0:.2f}%\n"
        f"{get_message(user.language, 'remaining_tenure')}: {user.remaining_tenure or user.tenure or 0} {get_message(user.language, 'years')}\n"
    )

    try:
        conversation = [
            {
                "role": "system",
                "content": (
                    f"{get_message(user.language, 'system_message1')}\n{context}"
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
            temperature=0.7,
            max_tokens=300
        )

        reply = response.choices[0].message.content.strip()
        send_messenger_message(messenger_id, {"text": reply})
        logging.debug("FAQ response generated and sent to user.")

    except Exception as e:
        logging.error(f"Error handling FAQ: {e}")
        error_message = {
            "text": get_message(user.language, "error_message")
        }
        send_messenger_message(messenger_id, error_message)
        logging.debug("Error occurred while handling FAQ. Directed user to admin.")

    # Update session state
    user.state = STATES['WAITING_INPUT']
    db.session.commit()

    # Notify admin
    notify_admin(user, f"{get_message(user.language, 'faq_query_received')}: {user_input}")
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
            f"📊 {get_message(user.language, 'event_name')}: {event_name}\n"
            f"{get_message(user.language, 'customer')}: {user.name or 'N/A'}\n"
            f"{get_message(user.language, 'contact')}: {user.phone_number or 'N/A'}\n\n"
            f"{summary}"
        )
    else:
        # Basic notification without summary
        comparison = (
            f"📊 {get_message(user.language, 'event_name')}: {event_name}\n"
            f"{get_message(user.language, 'customer')}: {user.name}\n"
            f"{get_message(user.language, 'contact')}: {user.phone_number}\n"
            f"{get_message(user.language, 'state')}: {user.state}\n"
            f"{get_message(user.language, 'no_loan_calculation')}"
        )

    send_messenger_message(admin_id, {"text": comparison})
    logging.debug("Admin notification sent.")

# Unhandled State Handler
def handle_unhandled_state(user: User, messenger_id: str, user_input: str):
    """
    Handles any unhandled states gracefully.
    """
    message = {
        "text": get_message(user.language, 'unhandled_state_message')
    }
    send_messenger_message(messenger_id, message)
    logging.debug("Unhandled state encountered. Prompted user to restart.")

    # Optionally, reset the user state to a known state
    user.state = STATES['END']
    db.session.commit()


def send_messenger_message(recipient_id, message, user_language='en'):
    """
    Sends a message to the user via Facebook Messenger API with language support.

    Parameters:
    - recipient_id (str): The Facebook ID of the recipient.
    - message (dict): The message payload containing 'text' and optionally 'quick_replies'.
    - user_language (str): The language of the user to fetch language-specific strings.
    """
    try:
        logging.debug(f"Recipient ID: {recipient_id}")
        url = f"https://graph.facebook.com/v16.0/me/messages?access_token={os.getenv('PAGE_ACCESS_TOKEN')}"
        headers = {"Content-Type": "application/json"}

        # Handle dynamic message translation
        if isinstance(message, str):
            # Simple text message
            message = get_message(user_language, message)  # Translate text message
            data = {
                "recipient": {"id": recipient_id},
                "message": {"text": message}
            }
        elif isinstance(message, dict):
            # Process quick replies or other message components
            if 'text' in message:
                message['text'] = get_message(user_language, message['text'])  # Translate text in the message
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
    STATES['LANGUAGE_SELECTION']: handle_language_selection,  # New handler for language selection
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
                # Create new user with default state (language selection)
                user = User(
                    messenger_id=sender_id,
                    name="Unknown",
                    phone_number="Unknown",
                    language='en',  # Default to English
                    state=STATES['LANGUAGE_SELECTION']  # Start with language selection
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

            # Main Logic Flow
            if not user.state:
                user.state = STATES['LANGUAGE_SELECTION']  # Language selection is the first state
                db.session.commit()
                logging.debug("User state was None. Set to LANGUAGE_SELECTION.")
            
            # Call the appropriate state handler based on the user's current state
            state_handler = STATE_HANDLERS.get(user.state, handle_unhandled_state)
            state_handler(user, sender_id, user_input)

            # Update last interaction timestamp
            user.last_interaction = datetime.utcnow()
            db.session.commit()

        return jsonify({"status": "success"}), 200

    except Exception as e:
        logging.error(f"Error in process_message: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500
def check_user_idle(user):
    # Assume user.last_interaction is a datetime field in the User model
    if user.last_interaction:
        now = datetime.utcnow()
        time_difference = now - user.last_interaction
        if time_difference > timedelta(days=1):  # If the user is idle for more than 24 hours
            return True
    return False

def send_welcome_back_message(messenger_id, user_language):
    """
    Sends a welcome back message in the user's preferred language.
    """
    messages = {
        'en': "Hi, welcome back! 👋\n\nIf you need to calculate again, please type 'restart'.",
        'ms': "Hai, selamat datang kembali! 👋\n\nJika anda perlu kira semula, sila taip 'restart'.",
        'zh': "你好，欢迎回来！👋\n\n如果你需要重新计算，请输入'restart'。"
    }

    # Default to English if the language is not found
    message_text = messages.get(user_language, messages['en'])

    message = {
        "text": message_text
    }
    send_messenger_message(messenger_id, message)
    logging.debug(f"Sent 'Welcome back' message to user in {user_language}.")
def reset_user(user: User):
    """
    Resets the user's information to start over with the current language.
    If no language is set, it defaults to English.
    """
    user.name = "Unknown"
    user.phone_number = "Unknown"
    
    # Retain the user's language, default to 'en' if not set
    user.language = user.language if user.language else 'en'
    
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
    logging.debug(f"User data reset to initial state with language set to {user.language}.")
