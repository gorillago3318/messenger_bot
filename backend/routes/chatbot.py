# Keep existing logging setup at the top
import logging

# System imports
import json
import traceback
import os
import pytz

# Flask imports
from flask import Blueprint, request, jsonify

# Set up Blueprint
chatbot_bp = Blueprint('chatbot', __name__)

# Custom project imports
from backend.utils.calculation import calculate_refinance_savings
from backend.utils.messenger import send_messenger_message
from backend.models import Users as User, Lead, ChatflowTemp, ChatLog
from backend.extensions import db
import openai  # Correctly import the openai module
from backend.utils.presets import get_preset_response
from datetime import datetime

MYT = pytz.timezone('Asia/Kuala_Lumpur')  # Malaysia timezone

# -------------------
# 1) Logging Setup
# -------------------
logging.basicConfig(
    level=logging.DEBUG,  # For verbose debug logs
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),      # Console output
        logging.FileHandler("debug.log")  # Save logs to debug.log
    ]
)

# -------------------
# 2) Initialize OpenAI client
# -------------------
openai.api_key = os.getenv("OPENAI_API_KEY").strip()
logging.debug(f"API Key: {openai.api_key}") # Set it directly or via environment variable

# -------------------
# 3) Load Language Files
# -------------------
try:
    with open('backend/routes/languages/en.json', 'r', encoding='utf-8') as f:
        EN_MESSAGES = json.load(f)
    logging.info(f"Successfully loaded en.json with {len(EN_MESSAGES)} keys.")
except Exception as e:
    logging.error(f"Error loading en.json file: {e}")
    EN_MESSAGES = {}

try:
    with open('backend/routes/languages/ms.json', 'r', encoding='utf-8') as f:
        MS_MESSAGES = json.load(f)
    logging.info(f"Successfully loaded ms.json with {len(MS_MESSAGES)} keys.")
except Exception as e:
    logging.error(f"Error loading ms.json file: {e}")
    MS_MESSAGES = {}

try:
    with open('backend/routes/languages/zh.json', 'r', encoding='utf-8') as f:
        ZH_MESSAGES = json.load(f)
    logging.info(f"Successfully loaded zh.json with {len(ZH_MESSAGES)} keys.")
except Exception as e:
    logging.error(f"Error loading zh.json file: {e}")
    ZH_MESSAGES = {}

LANGUAGE_OPTIONS = {
    'en': EN_MESSAGES,
    'ms': MS_MESSAGES,
    'zh': ZH_MESSAGES
}

# Example route to test blueprint
@chatbot_bp.route('/test', methods=['GET'])
def test():
    return jsonify({"message": "Chatbot BP is working!"}), 200

# Utility function for numeric validation
def is_valid_number(input_text, min_val=None, max_val=None, decimal_allowed=False):
    """Generic number validation with optional range and decimal checks."""
    if decimal_allowed:
        valid = input_text.replace('.', '', 1).isdigit()
    else:
        valid = input_text.isdigit()
    
    if not valid:
        return False
    
    value = float(input_text)
    if min_val is not None and value < min_val:
        return False
    if max_val is not None and value > max_val:
        return False
    
    return True

# -------------------
# Validation Functions
# -------------------

def validate_language_choice(input_text, user_data=None):
    """Validate language selection."""
    logging.debug(f"🔍 Validating language input: {input_text}")
    valid = input_text in ['1', '2', '3']
    if not valid:
        logging.warning(f"❌ Invalid language input: {input_text}")
    return valid


def validate_name(input_text, user_data=None):
    """Validate name contains only letters and spaces."""
    valid = input_text.replace(' ', '').isalpha()
    if not valid:
        logging.warning(f"❌ Invalid name: {input_text}")
    return valid


def validate_phone_number(input_text, user_data=None):
    """Validate phone number format."""
    if not input_text.isdigit():
        logging.warning(f"❌ Phone number must be numeric: {input_text}")
        return False

    if not input_text.startswith('01'):
        logging.warning(f"❌ Invalid phone number (must start with '01'): {input_text}")
        return False

    if len(input_text) not in [10, 11]:
        logging.warning(f"❌ Invalid phone number length (must be 10–11 digits): {input_text}")
        return False

    return True


def validate_age(input_text, user_data=None):
    """Validate age between 18 and 70."""
    if not is_valid_number(input_text, 18, 70):
        logging.warning(f"❌ Invalid age: {input_text}")
        return False
    return True


def validate_loan_amount(input_text, user_data=None):
    """Validate loan amount (numeric, no commas)."""
    clean_input = input_text.replace(',', '')
    valid = clean_input.isdigit()
    if not valid:
        logging.warning(f"❌ Invalid loan amount: {input_text}")
    return valid


def validate_loan_tenure(input_text, user_data=None):
    """Validate loan tenure between 1 and 40 years."""
    if not is_valid_number(input_text, 1, 40):
        logging.warning(f"❌ Invalid loan tenure: {input_text}")
        return False
    return True


def validate_monthly_repayment(input_text, user_data=None):
    """Validate monthly repayment as numeric."""
    if not is_valid_number(input_text, decimal_allowed=True):
        logging.warning(f"❌ Invalid monthly repayment: {input_text}")
        return False
    return True


def validate_interest_rate(input_text, user_data=None):
    """Validate interest rate (3%–10%) or 'skip'."""
    if input_text.lower() == 'skip':  # Allow skipping
        return True

    if not is_valid_number(input_text, 3, 10, decimal_allowed=True):
        logging.warning(f"❌ Invalid interest rate: {input_text}")
        return False
    return True


def validate_remaining_tenure(input_text, user_data=None):
    """Validate remaining tenure as numeric or 'skip'."""
    if input_text.lower() == 'skip':
        return True

    if not is_valid_number(input_text, 1):
        logging.warning(f"❌ Invalid remaining tenure: {input_text}")
        return False
    return True


def log_chat(sender_id, user_message, bot_message, user_data=None):
    """Logs user-bot conversations into ChatLog."""
    try:
        # Fallback values for user data
        name = getattr(user_data, 'name', 'Unknown User') if user_data else 'Unknown User'
        phone_number = getattr(user_data, 'phone_number', 'Unknown') if user_data else 'Unknown'

        # Check if user already exists
        user = User.query.filter_by(messenger_id=sender_id).first()

        # If the user doesn't exist, create one
        if not user:
            user = User(
                messenger_id=sender_id,
                name=name,
                phone_number=phone_number
            )
            db.session.add(user)
            db.session.commit()  # Commit new user creation

        # Create chat log entry
        chat_log = ChatLog(
            user_id=user.id,
            sender_id=sender_id,
            name=name,
            phone_number=phone_number,
            message_content=f"User: {user_message}\nBot: {bot_message}",
            created_at=datetime.now(MYT)  # Correct datetime usage
        )
        db.session.add(chat_log)
        db.session.commit()

        # Log success
        logging.info(f"✅ Chat logged for user {sender_id}")

    except Exception as e:
        # Log error and rollback if insertion fails
        logging.error(f"❌ Error logging chat: {str(e)}")
        db.session.rollback()


# -------------------
# 5) Step Configuration
# -------------------

def validate_mode_selection(x, user_data=None):
    """Validate mode selection input."""
    return x in ['1', '2']

STEP_CONFIG = {
    # Step 1: Language Selection
    'choose_language': {
        'message': "choose_language_message",  # Message prompts user to choose language
        'next_step_map': {
            '1': 'get_name',  # English
            '2': 'get_name',  # Malay
            '3': 'get_name'   # Chinese
        },
        'next_step': None,
        'validator': lambda x: x in ['1', '2', '3']  # Validate input for 1, 2, or 3
    },

    # Step 2: Get Name
    'get_name': {
        'message': 'name_message',
        'next_step': 'get_phone_number',
        'validator': lambda x: x.replace(' ', '').isalpha()  # Validate alphabetic input
    },

    # Step 3: Get Phone Number
    'get_phone_number': {
        'message': 'phone_number_message',
        'next_step': 'get_age',
        'validator': lambda x: x.isdigit() and len(x) in [10, 11] and x.startswith('01')  # Starts with '01' and 10–11 digits
    },

    # Step 4: Get Age
    'get_age': {
        'message': 'age_message',
        'next_step': 'get_loan_amount',
        'validator': lambda x: x.isdigit() and 18 <= int(x) <= 70  # Age between 18–70
    },

    # Step 5: Get Loan Amount
    'get_loan_amount': {
        'message': 'loan_amount_message',
        'next_step': 'get_loan_tenure',
        'validator': lambda x: x.replace(',', '').isdigit() and int(x.replace(',', '')) > 0  # Positive numeric value
    },

    # Step 6: Get Loan Tenure
    'get_loan_tenure': {
        'message': 'loan_tenure_message',
        'next_step': 'get_monthly_repayment',
        'validator': lambda x: x.isdigit() and 1 <= int(x) <= 40  # Between 1–40 years
    },

    # Step 7: Get Monthly Repayment
    'get_monthly_repayment': {
        'message': 'repayment_message',
        'next_step': 'get_interest_rate',
        'validator': lambda x: x.replace('.', '', 1).isdigit() and float(x) > 0  # Positive numeric with decimals allowed
    },

    # Step 8: Get Interest Rate
    'get_interest_rate': {
        'message': 'interest_rate_message',
        'next_step': 'get_remaining_tenure',
        'validator': lambda x: x.lower() == 'skip' or (x.replace('.', '', 1).isdigit() and 3 <= float(x) <= 10)  # 3–10% or 'skip'
    },

    # Step 9: Get Remaining Tenure
    'get_remaining_tenure': {
        'message': 'remaining_tenure_message',
        'next_step': 'process_completion',
        'validator': lambda x: x.lower() == 'skip' or (x.isdigit() and int(x) > 0)  # Positive integer or 'skip'
    },

    # Step 10: Process Completion
    'process_completion': {
        'message': 'completion_message',
        'next_step': 'gpt_query_mode',
        'validator': lambda x: True  # Always passes
    },

    # GPT Query Mode for Inquiries
    'gpt_query_mode': {
        'message': 'inquiry_mode_message',  # Fetch dynamically from language files
        'next_step': None,
        'validator': lambda x: True  # Always passes
    }
}


# -------------------
# 6) Utility Functions
# -------------------

def get_message(key, language_code, mode='flow'):
    """
    Retrieve a message from the appropriate language file based on language and mode.
    Supports fallback to English for missing messages and guides the user.
    """
    try:
        # Map numeric language codes to text codes
        LANGUAGE_MAP = {'1': 'en', '2': 'ms', '3': 'zh'}
        language_code = LANGUAGE_MAP.get(language_code, 'en')  # Default to English

        # Retrieve the message key for the mode
        messages = LANGUAGE_OPTIONS.get(language_code, LANGUAGE_OPTIONS['en'])  # Select language file

        # Fetch the message
        message = messages.get(key)

        # Log the key lookup for debugging
        logging.debug(f"🔍 Message Key Lookup: {key}, Language: {language_code}, Found: {message}")

        # Final fallback to English if key is still not found
        if not message:
            logging.warning(f"⚠️ Missing key '{key}' in '{language_code}', falling back to English.")
            message = LANGUAGE_OPTIONS['en'].get(key, "⚠️ Invalid input. Please check and try again.")

        return message

    except Exception as e:
        logging.error(f"❌ Error in get_message: {str(e)}")
        return "⚠️ An error occurred. Please try again."


def delete_chatflow_data(messenger_id):
    """
    Delete all chatflow data for a specific user by messenger_id.
    Includes error handling with rollback.
    """
    try:
        # Attempt to delete user data
        ChatflowTemp.query.filter_by(messenger_id=messenger_id).delete()
        db.session.commit()
        logging.info(f"✅ Deleted chatflow data for messenger_id {messenger_id}.")
    except Exception as e:
        db.session.rollback()
        logging.error(f"❌ Failed to delete chatflow data for {messenger_id}: {str(e)}")


def reset_user_data(user_data, mode='flow'):
    """
    Reset user data based on the selected mode (flow or inquiry).
    """
    try:
        if mode == 'flow':
            user_data.current_step = 'choose_language'  # Start with language selection
            user_data.language_code = 'en'
            user_data.name = None
            user_data.phone_number = None
            user_data.age = None
            user_data.original_loan_amount = None
            user_data.original_loan_tenure = None
            user_data.current_repayment = None
            user_data.interest_rate = None
            user_data.remaining_tenure = None
            user_data.mode = 'flow'
        elif mode == 'inquiry':
            user_data.current_step = 'inquiry_mode'
            user_data.mode = 'inquiry'
            user_data.gpt_query_count = 0
            user_data.last_question_time = None

        db.session.commit()
        logging.info(f"✅ Reset user data for {user_data.messenger_id} in {mode} mode.")
    except Exception as e:
        db.session.rollback()
        logging.error(f"❌ Failed to reset user data for {user_data.messenger_id}: {str(e)}")

def process_user_input(current_step, user_data, message_body, messenger_id):
    """
    Process user input and store it in ChatflowTemp with separate columns.
    Supports Refinance Flow.
    """
    try:
        logging.debug(f"Processing step: {current_step} with input: {message_body}")

        # ----------------------------
        # Handle 'Get Started' directly
        # ----------------------------
        if current_step == 'get_started':
            # Redirect to language selection step
            user_data.current_step = 'choose_language'
            db.session.commit()
            return {"status": "success", "next_step": 'choose_language'}, 200

        # ----------------------------
        # Handle 'skip' Command Before Validation
        # ----------------------------
        if message_body.lower() == 'skip':
            logging.info(f"🔄 Skipping input for step: {current_step}")
            step_config = STEP_CONFIG.get(current_step, {})
            next_step_config = step_config.get('next_step')

            if 'next_step_map' in step_config:
                logging.error(f"❌ Cannot skip a step that requires a specific next step mapping.")
                return {"status": "error", "message": "Cannot skip this step. Please provide a valid input."}, 400
            else:
                next_step = next_step_config

            # Move user to the next step and commit changes
            user_data.current_step = next_step
            db.session.commit()
            logging.debug(f"🔄 Moved to next step: {next_step}")
            return {"status": "success", "next_step": next_step}, 200

        # ----------------------------
        # 2. Initialize Update Data
        # ----------------------------
        data_to_update = {}
        logging.debug(f"📥 Processing input for step: {current_step} with message: {message_body}")

        # ----------------------------
        # Handle immediate language update for 'choose_language'
        if current_step == 'choose_language':
            # Validate input first
            if message_body not in ['1', '2', '3']:
                invalid_msg = get_message('invalid_language_choice_message', user_data.language_code)
                send_messenger_message(messenger_id, invalid_msg)
                return {"status": "failed"}, 200

            # Update language code immediately after validation
            language_mapping = {'1': 'en', '2': 'ms', '3': 'zh'}
            selected_language = language_mapping.get(message_body, 'en')
            user_data.language_code = selected_language
            db.session.commit()

            # Log the selected language
            logging.debug(f"✅ Language updated to: {selected_language}")

        # ----------------------------
        # 3. Process Steps with Validation
        # ----------------------------
        step_config = STEP_CONFIG.get(current_step)
        if not step_config:
            logging.error(f"❌ Step configuration not found for step: {current_step}")
            return {"status": "error", "message_key": 'unknown_step'}, 500

        # Validate input before updates
        validator = step_config.get('validator')
        if not validator or not validator(message_body):
            logging.warning(f"❌ Validation failed for step: {current_step} with input: {message_body}")
            # Get error message dynamically based on language
            error_key = f"invalid_{current_step}_message"
            invalid_msg = get_message(error_key, user_data.language_code)

            # Fallback to general invalid message if key is missing
            if invalid_msg == "Message not available.":
                invalid_msg = get_message('invalid_input_message', user_data.language_code)

            # Send localized error message
            send_messenger_message(messenger_id, invalid_msg)
            return {"status": "failed"}, 200

        # Determine the next step based on whether 'next_step_map' exists
        if 'next_step_map' in step_config:
            next_step = step_config['next_step_map'].get(message_body)
            if not next_step:
                logging.error(f"❌ Invalid input '{message_body}' for step '{current_step}'")
                error_key = f"invalid_{current_step}_message"
                invalid_msg = get_message(error_key, user_data.language_code)
                if invalid_msg == "Message not available.":
                    invalid_msg = get_message('invalid_input_message', user_data.language_code)
                send_messenger_message(messenger_id, invalid_msg)
                return {"status": "error", "message": "Invalid step transition"}, 400
        else:
            next_step = step_config.get('next_step')

        # ----------------------------
        # 4. Update User Data Based on Current Step
        # ----------------------------
        update_mapping = {
            'choose_language': lambda x: {'language_code': {'1': 'en', '2': 'ms', '3': 'zh'}.get(x, 'en')},
            'get_name': lambda x: {'name': x.title()},
            'get_phone_number': lambda x: {'phone_number': str(x) if x.startswith('01') and len(x) in [10, 11] else None},
            'get_age': lambda x: {'age': int(x)},
            'get_loan_amount': lambda x: {'original_loan_amount': float(x.replace(',', ''))},
            'get_loan_tenure': lambda x: {'original_loan_tenure': int(x)},
            'get_monthly_repayment': lambda x: {'current_repayment': float(x)},
            'get_interest_rate': lambda x: {'interest_rate': None if x.lower() == 'skip' else float(x)},
            'get_remaining_tenure': lambda x: {'remaining_tenure': None if x.lower() == 'skip' else int(x)}
        }

        # Apply updates
        if current_step in update_mapping:
            updates = update_mapping[current_step](message_body)
            if updates.get('phone_number') is None and current_step == 'get_phone_number':
                error_msg = get_message('invalid_phone_number_message', user_data.language_code)
                if error_msg == "Message not available.":
                    error_msg = get_message('invalid_phone_number_message', 'en')
                send_messenger_message(messenger_id, error_msg)
                return {"status": "failed"}, 200
            data_to_update.update(updates)

        # ----------------------------
        # 5. Update User Data in Database
        # ----------------------------
        for key, value in data_to_update.items():
            setattr(user_data, key, value)

        user_data.current_step = next_step
        db.session.commit()

        logging.debug(f"🔄 Moved to next step: {next_step}")
        return {"status": "success", "next_step": next_step}, 200

    except Exception as e:
        logging.error(f"❌ Error in process_user_input: {str(e)}")
        logging.error(f"Traceback: {traceback.format_exc()}")
        db.session.rollback()
        return {"status": "error", "message": "An error occurred while processing your input."}, 500


@chatbot_bp.route('/process_message', methods=['POST'])
def process_message():
    try:
        # ----------------------------
        # 1. Parse Incoming Data
        # ----------------------------
        data = request.get_json()
        logging.debug(f"🛢 Received raw request data:\n{json.dumps(data, indent=2)}")

        # Extract Sender ID
        sender_id = None
        messenger_id = None

        # Fix sender ID extraction
        messaging_event = data.get('entry', [{}])[0].get('messaging', [{}])[0]
        sender_id = messaging_event.get('sender', {}).get('id')
        messenger_id = sender_id

        # Validate sender ID
        if not sender_id:
            logging.error("❌ Missing sender ID in incoming request.")
            return jsonify({"status": "error", "message": "Missing sender ID"}), 400

        # ----------------------------
        # 2. Extract Message Content
        # ----------------------------
        message_data = messaging_event.get('message', {})
        postback_data = messaging_event.get('postback', {})

        # Initialize message_body
        message_body = None

        # ----------------------------
        # Handle 'Get Started' Payload
        # ----------------------------
        if 'payload' in postback_data:
            message_body = postback_data['payload'].strip().lower()

            if message_body == 'get_started':
                logging.info(f"🌟 User {sender_id} clicked the 'Get Started' button.")
                # Create or reset user data here
                user_data = db.session.query(ChatflowTemp).filter_by(messenger_id=sender_id).first()

                if user_data:
                    reset_user_data(user_data, mode='flow')  # Reset state
                else:
                    # Create new user session
                    user_data = ChatflowTemp(
                        sender_id=sender_id,
                        messenger_id=messenger_id,
                        current_step='choose_language',  # Start with language selection
                        language_code='en',
                        mode='flow'
                    )
                    db.session.add(user_data)
                    db.session.commit()

                # Send the "choose language" message
                choose_language_message = get_message('choose_language_message', 'en')  # Fetch from en.json
                send_messenger_message(sender_id, choose_language_message)
                return jsonify({"status": "success"}), 200

        # Extract message body from other types of messages (text or quick replies)
        if not message_body:
            if 'quick_reply' in message_data:
                message_body = message_data['quick_reply']['payload'].strip().lower()
            elif 'text' in message_data:
                message_body = message_data['text'].strip()

        # If we have no message content, we can't proceed, so we log and return an error
        if not message_body:
            logging.error(f"❌ No valid message found from {sender_id}")
            send_messenger_message(sender_id, "Sorry, I can only process text or button replies for now.")
            return jsonify({"status": "error", "message": "No valid message found"}), 400

        logging.info(f"💎 Incoming message from {sender_id}: {message_body}")

        # ----------------------------
        # 3. Retrieve or Create User Data
        # ----------------------------
        user_data = db.session.query(ChatflowTemp).filter_by(messenger_id=sender_id).first()

        # Handle "Restart" Commands and further steps
        if message_body.lower() in ['restart', 'reset', 'start over']:
            logging.info(f"🔄 Restarting flow for user {sender_id}")
            reset_user_data(user_data, mode='flow')  # Use helper function to reset
            restart_msg = get_message('choose_language_message', 'en')  # Start with language selection
            send_messenger_message(sender_id, restart_msg)
            log_chat(sender_id, message_body, restart_msg, user_data)
            return jsonify({"status": "success"}), 200

        # ----------------------------
        # Handle Inquiry Mode
        # ----------------------------
        if user_data.mode == 'inquiry':
            logging.info(f"💬 Inquiry mode for user {sender_id}")
            try:
                response = handle_gpt_query(message_body, user_data, messenger_id)
            except Exception as e:
                logging.error(f"❌ GPT query error: {str(e)}")
                response = get_message('inquiry_mode_message', user_data.language_code)  # Proper fallback
            log_chat(sender_id, message_body, response, user_data)
            send_messenger_message(sender_id, response)
            return jsonify({"status": "success"}), 200

        # ----------------------------
        # Continue Processing the Regular Flow
        # ----------------------------

        # Process other user inputs, like choosing language or mode
        current_step = user_data.current_step
        process_response, status = process_user_input(current_step, user_data, message_body, messenger_id)

        if status != 200:
            # Get specific error message for invalid input from en.json
            error_key = f"invalid_{current_step}_message"
            invalid_msg = get_message(error_key, user_data.language_code)
            send_messenger_message(sender_id, invalid_msg)
            return jsonify({"status": "error"}), 500

        # Handle next step
        next_step = process_response.get("next_step")
        if next_step:
            user_data.current_step = next_step
            db.session.commit()

            # Send the next message or process completion
            if next_step != 'process_completion':
                next_message = get_message(next_step, user_data.language_code)
                send_messenger_message(sender_id, next_message)
                log_chat(sender_id, message_body, next_message, user_data)
            else:
                # Process completion step and generate summary
                send_messenger_message(sender_id, get_message('completion_message', user_data.language_code))
                result = handle_process_completion(messenger_id)
                if result[1] != 200:
                    send_messenger_message(sender_id, "Sorry, we encountered an error processing your request. Please restart the process.")
                else:
                    user_data.mode = 'inquiry'  # Ensure mode is set to inquiry
                    db.session.commit()
                    follow_up_message = get_message('inquiry_mode_message', user_data.language_code)
                    send_messenger_message(sender_id, follow_up_message)
                return jsonify({"status": "success"}), 200

        return jsonify({"status": "success"}), 200

    except Exception as e:
        logging.error(f"❌ Error in process_message: {str(e)}")
        logging.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"status": "error", "message": "Something went wrong."}), 500



def handle_process_completion(messenger_id):
    """Handles the final step and calculates refinance savings."""
    logging.debug(f"🚀 Entered handle_process_completion() for Messenger ID: {messenger_id}")

    try:
        # Step 1: Fetch user data
        user_data = db.session.query(ChatflowTemp).filter_by(messenger_id=messenger_id).first()
        if not user_data:
            logging.error(f"❌ No user_data found for messenger_id: {messenger_id}")
            return jsonify({"status": "error", "message": "No user data found"}), 404

        # Log user data for debugging
        logging.debug(f"🔍 Messenger ID: {messenger_id}")
        logging.debug(f"📊 User Data - Loan Amount: {user_data.original_loan_amount}, "
                      f"Loan Tenure: {user_data.original_loan_tenure}, "
                      f"Monthly Repayment: {user_data.current_repayment}")

        # Step 2: Validate required inputs
        if not all([user_data.original_loan_amount, user_data.original_loan_tenure, user_data.current_repayment]):
            logging.error("❌ Missing required user data for calculation.")
            send_messenger_message(
                messenger_id,
                "Sorry, we are missing some details. Please restart the process by typing 'restart'."
            )
            return jsonify({"status": "error", "message": "Missing required data"}), 400

        # Step 3: Perform refinance savings calculation
        results = calculate_refinance_savings(
            user_data.original_loan_amount,
            user_data.original_loan_tenure,
            user_data.current_repayment
        )

        # Check if calculation returned results
        if not results:
            logging.error(f"❌ Calculation failed for messenger_id: {messenger_id}")
            send_messenger_message(
                messenger_id,
                "We couldn't calculate your savings. Please try again later or contact our admin for assistance."
            )
            return jsonify({"status": "error", "message": "Calculation failed"}), 500

        # Step 4: Extract savings data
        monthly_savings = round(float(results.get('monthly_savings', 0.0)), 2)
        yearly_savings = round(float(results.get('yearly_savings', 0.0)), 2)
        lifetime_savings = round(float(results.get('lifetime_savings', 0.0)), 2)
        years_saved = results.get('years_saved', 0)
        months_saved = results.get('months_saved', 0)

        logging.debug(f"💰 Savings - Monthly: {monthly_savings} RM, Yearly: {yearly_savings} RM, Lifetime: {lifetime_savings} RM")
        logging.debug(f"⏱️ Time Saved - Years: {years_saved}, Months: {months_saved}")

        # Step 5: Handle cases with no savings
        if monthly_savings <= 0:
            msg = (
                "Thank you for using FinZo AI! Our analysis shows your current loan rates are already great. "
                "We’ll be in touch if better offers become available.\n\n"
                "💬 Need help? Contact our admin or type 'inquiry' to chat."
            )
            send_messenger_message(messenger_id, msg)
            user_data.mode = 'inquiry'  # Corrected mode name
            db.session.commit()
            logging.info(f"✅ No savings found. Switched user {messenger_id} to inquiry mode.")
            return jsonify({"status": "success"}), 200

        # Step 6: Generate and send summary messages
        summary_messages = prepare_summary_messages(user_data, results, user_data.language_code or 'en')
        for m in summary_messages:
            try:
                send_messenger_message(messenger_id, m)
            except Exception as e:
                logging.error(f"❌ Failed to send summary message to {messenger_id}: {str(e)}")

        # Step 7: Notify admin about the new lead
        try:
            send_new_lead_to_admin(messenger_id, user_data, results)
        except Exception as e:
            logging.error(f"❌ Failed to notify admin: {str(e)}")

        # Step 8: Save results in the database
        try:
            update_database(messenger_id, user_data, results)
        except Exception as e:
            logging.error(f"❌ Failed to save results in database: {str(e)}")

        # Step 9: Switch to inquiry mode
        user_data.mode = 'inquiry'  # Corrected mode name
        db.session.commit()
        logging.info(f"✅ Process completed successfully for {messenger_id}. Switched to inquiry mode.")

        return jsonify({"status": "success"}), 200

    except Exception as e:
        # Step 10: Error handling
        logging.error(f"❌ Error in handle_process_completion: {str(e)}")
        logging.error(f"Traceback: {traceback.format_exc()}")
        db.session.rollback()
        send_messenger_message(
            messenger_id,
            "An error occurred. Please restart the process by typing 'restart'."
        )
        return jsonify({"status": "error", "message": "An error occurred."}), 500


def prepare_summary_messages(user_data, calc_results, language_code):
    """Builds shortened summary messages about the user's savings."""

    try:
        # Retrieve WhatsApp link from environment variable
        whatsapp_link = os.getenv('ADMIN_WHATSAPP_LINK', "https://wa.me/60167177813")

        # Format values
        current_repayment = f"RM {float(user_data.current_repayment):,.2f}"
        new_repayment = f"RM {float(calc_results.get('new_monthly_repayment', 0.0)):,.2f}"
        monthly_savings = f"RM {float(calc_results.get('monthly_savings', 0.0)):,.2f}"
        yearly_savings = f"RM {float(calc_results.get('yearly_savings', 0.0)):,.2f}"
        lifetime_savings = f"RM {float(calc_results.get('lifetime_savings', 0.0)):,.2f}"

        # Calculate equivalent years and months saved
        months_saved = 0
        years_saved = 0
        remaining_months = 0

        # If current repayment is 0, we handle it as no savings
        if user_data.current_repayment > 0:
            months_saved = calc_results.get('lifetime_savings', 0) / user_data.current_repayment
            years_saved = months_saved // 12  # Calculate full years
            remaining_months = months_saved % 12  # Calculate remaining months
        else:
            months_saved = 0
            years_saved = 0
            remaining_months = 0

        # Combined Summary (Merges Summary 1 and 2)
        summary_msg = (
            f"📊 Savings Summary:\n\n"
            f"💸 **Current Repayment:** {current_repayment}\n"
            f"💸 **New Repayment:** {new_repayment}\n"
            f"💰 **Monthly Savings:** {monthly_savings}\n"
            f"💰 **Yearly Savings:** {yearly_savings}\n"
            f"🎉 **Lifetime Savings:** {lifetime_savings}\n\n"
            f"⏳ *Equivalent to saving {int(years_saved)} year(s) and {int(remaining_months)} month(s) of repayments!* 🚀"
        )

        # What's Next Message
        whats_next_msg = (
            "🔜 **What's Next?**\n\n"
            "One of our specialists will contact you shortly to assist with your refinancing options.\n"
            f"If you need urgent assistance, contact us directly at {whatsapp_link}."
        )

        # Return merged messages
        return [summary_msg, whats_next_msg]

    except Exception as e:
        logging.error(f"❌ Error preparing summary messages: {str(e)}")
        return ["Error: Failed to generate summary messages. Please contact support."]


def update_database(messenger_id, user_data, calc_results):
    """Save user data and calculations to the database."""
    try:
        # Fetch or create user record
        user = User.query.filter_by(messenger_id=messenger_id).first()
        if not user:
            logging.warning(f"User not found for messenger_id: {messenger_id}. Creating new user.")
            user = User(
                messenger_id=messenger_id,
                name=user_data.name or "Unknown",
                age=user_data.age or 0,
                phone_number=user_data.phone_number or "Unknown"  # Add phone_number here
            )
            db.session.add(user)
            db.session.flush()  # Flush to get user.id

        else:
            # Update existing user with new phone number if available
            if user_data.phone_number:
                user.phone_number = user_data.phone_number
                logging.debug(f"Updated phone_number for user {messenger_id}: {user.phone_number}")

        if not user.id:
            logging.error(f"Failed to create or fetch user for messenger_id: {messenger_id}.")
            return

        # Add lead entry
        lead = Lead(
            user_id=user.id,
            sender_id=messenger_id,  # Ensure sender_id is passed
            name=user_data.name,
            phone_number=user_data.phone_number,  # Add phone_number here
            original_loan_amount=user_data.original_loan_amount,
            original_loan_tenure=user_data.original_loan_tenure,
            current_repayment=user_data.current_repayment,
            new_repayment=round(calc_results.get('new_monthly_repayment', 0.0), 2),
            monthly_savings=round(calc_results.get('monthly_savings', 0.0), 2),
            yearly_savings=round(calc_results.get('yearly_savings', 0.0), 2),
            total_savings=round(calc_results.get('lifetime_savings', 0.0), 2),
            years_saved=calc_results.get('years_saved', 0)
        )

        db.session.add(lead)
        db.session.commit()
        logging.info(f"✅ Database updated successfully for user {messenger_id}")

    except Exception as e:
        logging.error(f"❌ Error updating database for {messenger_id}: {str(e)}")
        db.session.rollback()

def send_new_lead_to_admin(messenger_id, user_data, calc_results):
    try:
        # Fetch Admin Messenger ID
        admin_messenger_id = os.getenv('ADMIN_MESSENGER_ID')
        if not admin_messenger_id:
            logging.error("⚠️ ADMIN_MESSENGER_ID not set in environment variables.")
            return

        # Calculate equivalent years and months saved (ensure months_saved is correct)
        months_saved = 0
        years_saved = 0
        remaining_months = 0

        # If current repayment is 0, handle as no savings
        if user_data.current_repayment > 0:
            months_saved = calc_results.get('lifetime_savings', 0) / user_data.current_repayment
            years_saved = months_saved // 12  # Calculate full years
            remaining_months = months_saved % 12  # Calculate remaining months
        else:
            months_saved = 0
            years_saved = 0
            remaining_months = 0

        # Format message with the correct savings data
        msg = (
            f"📢 **New Lead Alert!** 📢\n\n"
            f"👤 **Name:** {getattr(user_data, 'name', 'Unknown')}\n"
            f"📱 **Phone Number:** {getattr(user_data, 'phone_number', 'N/A')}\n"  # Include phone number
            f"💰 **Current Loan Amount:** RM {float(getattr(user_data, 'original_loan_amount', 0)):,.2f}\n"
            f"📅 **Current Tenure:** {getattr(user_data, 'original_loan_tenure', 'N/A')} years\n"
            f"📉 **Current Repayment:** RM {float(getattr(user_data, 'current_repayment', 0)):,.2f}\n"
            f"📈 **New Repayment:** RM {float(calc_results.get('new_monthly_repayment', 0)):,.2f}\n"
            f"💸 **Monthly Savings:** RM {float(calc_results.get('monthly_savings', 0)):,.2f}\n"
            f"💰 **Yearly Savings:** RM {float(calc_results.get('yearly_savings', 0)):,.2f}\n"
            f"🎉 **Total Savings:** RM {float(calc_results.get('lifetime_savings', 0)):,.2f}\n"
            f"🕒 **Years Saved:** {int(years_saved)} years\n"  # Using calculated years_saved
            f"📱 **Messenger ID:** {messenger_id}"
        )

        # Send message to admin
        send_messenger_message(admin_messenger_id, msg)
        logging.info(f"✅ Lead sent to admin successfully: {admin_messenger_id}")

    except Exception as e:
        logging.error(f"❌ Error sending lead to admin: {str(e)}")

# -------------------
# 9) GPT Query Handling
# -------------------
def handle_gpt_query(question, user_data, messenger_id):
    try:
        # Step 1: Check inquiry mode
        if user_data.mode != 'inquiry':
            logging.info(f"🚫 User {messenger_id} is not in inquiry mode. Ignoring GPT query.")
            return "Please complete the process before asking questions."

        # Step 2: Fetch preset response first
        response = get_preset_response(question, user_data.language_code or 'en')
        if response:
            logging.info(f"✅ Preset response found for query: {question}")
            return response  # Only return the preset response

        # Step 3: Query GPT only if no preset response is found
        logging.info(f"❌ No preset match. Querying GPT for: {question}")
        prompt = f"Question: {question}\nAnswer:"

        # Making GPT request
        openai_res = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant for home refinancing and home loan queries."},
                {"role": "user", "content": prompt}
            ]
        )

        reply = openai_res['choices'][0]['message']['content'].strip()
        logging.info(f"✅ GPT response received for user {messenger_id}: {reply}")

        # Return GPT Response (Message sent only once outside this function)
        return reply

    except Exception as e:
        logging.error(f"❌ Error in handle_gpt_query: {str(e)}")
        return "Sorry, something went wrong!"


def log_gpt_query(messenger_id, question, response):
    """Logs GPT queries to ChatLog."""
    try:
        messenger_id = str(messenger_id)
        user = User.query.filter_by(messenger_id=messenger_id).first()

        # Create or update user
        if not user:
            user = User(
                messenger_id=messenger_id,
                name="Unknown User",
                age=0,
                phone_number="Unknown"  # Default if not set
            )
            db.session.add(user)
            db.session.flush()
        else:
            if not user.name:
                user.name = "Unknown User"
            if not user.age:
                user.age = 0
            if not user.phone_number:
                user.phone_number = "Unknown"  # Default if not set

        # Log GPT query
        chat_log = ChatLog(
            user_id=user.id,
            message_content=f"User (GPT Query): {question}\nBot: {response}",
            phone_number=user.phone_number  # Ensure phone_number is set
        )
        db.session.add(chat_log)
        db.session.commit()
        logging.info(f"✅ GPT query logged for user {user.messenger_id}")
    except Exception as e:
        logging.error(f"❌ Error logging GPT query: {str(e)}")
        db.session.rollback()


# -------------------
# 11) Helper Messages
# -------------------
def send_limit_reached_message(messenger_id):
    """Sends a message when query limit is reached."""
    # Fetch WhatsApp link from environment
    whatsapp_link = os.getenv('ADMIN_WHATSAPP_LINK', 'https://wa.me/60167177813')
    msg = (
        "🚫 You've reached your daily limit of 15 questions.\n"
        "Your limit will reset in 24 hours. ⏰\n\n"
        f"💬 Need urgent help? Contact our admin at *{whatsapp_link}*"
    )
    try:
        send_messenger_message(messenger_id, msg)
        logging.info(f"✅ Limit reached message sent to user {messenger_id}")
    except Exception as e:
        logging.error(f"❌ Error sending limit reached message to {messenger_id}: {str(e)}")

def send_remaining_query_notification(messenger_id, questions_left):
    """Sends a notification about remaining GPT queries."""
    if questions_left <= 0:
        logging.warning(f"⚠️ Invalid questions left count ({questions_left}) for user {messenger_id}.")
        return

    msg = f"🤖 You have {questions_left} questions remaining today. 📊"
    try:
        send_messenger_message(messenger_id, msg)
        logging.info(f"✅ Notified user {messenger_id} of {questions_left} questions left.")
    except Exception as e:
        logging.error(f"❌ Error sending query count notification to {messenger_id}: {str(e)}")

def reset_query_count(user_data):
    """Resets the GPT query count for the user."""
    try:
        user_data.gpt_query_count = 0
        user_data.last_question_time = datetime.now()
        db.session.commit()
        logging.info(f"✅ Reset query count for user {user_data.messenger_id}")
    except Exception as e:
        logging.error(f"❌ Error resetting query count for user {user_data.messenger_id}: {str(e)}")
        db.session.rollback()

def notify_admin_about_gpt_query(messenger_id, question, user_data):
    """Sends a notification to admin about complex queries requiring attention."""
    try:
        # Get admin ID from environment variables
        admin_messenger_id = os.getenv('ADMIN_MESSENGER_ID')

        if not admin_messenger_id:
            logging.error("⚠️ ADMIN_MESSENGER_ID not set in environment variables.")
            return

        # Admin message with user details
        admin_msg = (
            f"📢 **Admin Alert - New Inquiry**\n\n"
            f"👤 **Name:** {user_data.name or 'Unknown'}\n"
            f"📱 **Phone Number:** {user_data.phone_number or 'N/A'}\n"
            f"❓ **Question:** {question}\n"
            f"🆔 **Messenger ID:** {messenger_id}\n\n"
            "📢 Please follow up with the user."
        )

        # Send message to admin
        send_messenger_message(admin_messenger_id, admin_msg)
        logging.info(f"✅ Admin notified for user {messenger_id}")

    except Exception as e:
        logging.error(f"❌ Failed to notify admin: {str(e)}")
