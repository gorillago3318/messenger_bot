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
from openai import OpenAI
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
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

# -------------------
# 4) Validation Functions
# -------------------

def validate_language_choice(input_text, user_data=None):
    """Validate that the user selects 1, 2, or 3 for language selection."""
    logging.debug(f"🔍 Validating language input: {input_text}")
    if input_text.lower() in ['hi', 'hello', 'hey']:
        return False  # Trigger language step again for greetings

    valid = input_text in ['1', '2', '3']
    if not valid:
        logging.warning(f"❌ Invalid language input: {input_text}")
    return valid



def validate_name(input_text, user_data=None):
    """Validate that the name contains only letters and spaces."""
    valid = input_text.replace(' ', '').isalpha()
    if not valid:
        logging.warning(f"❌ Invalid name: {input_text}")
    return valid


def validate_phone_number(input_text, user_data=None):
    """Validate that the phone number is numeric and at least 10 digits."""
    valid = input_text.isdigit() and len(input_text) >= 10
    if not valid:
        logging.warning(f"❌ Invalid phone number: {input_text}")
    return valid


def validate_age(input_text, user_data=None):
    """Validate that the age is between 18 and 70."""
    valid = input_text.isdigit() and 18 <= int(input_text) <= 70
    if not valid:
        logging.warning(f"❌ Invalid age: {input_text}")
    return valid


def validate_loan_amount(input_text, user_data=None):
    """Validate that the loan amount is numeric (ignores commas)."""
    clean_input = input_text.replace(',', '')
    valid = clean_input.isdigit()
    if not valid:
        logging.warning(f"❌ Invalid loan amount: {input_text}")
    return valid


def validate_loan_tenure(input_text, user_data=None):
    """Validate that the loan tenure is between 1 and 40 years."""
    valid = input_text.isdigit() and 1 <= int(input_text) <= 40
    if not valid:
        logging.warning(f"❌ Invalid loan tenure: {input_text}")
    return valid


def validate_monthly_repayment(input_text, user_data=None):
    """Validate that the monthly repayment is numeric."""
    valid = input_text.replace('.', '', 1).isdigit()
    if not valid:
        logging.warning(f"❌ Invalid monthly repayment: {input_text}")
    return valid


def validate_interest_rate(input_text, user_data=None):
    """Validate interest rate (3% to 10%) or allow 'skip'."""
    try:
        if input_text.lower() == 'skip':  # Allow skipping
            return True
        valid = input_text.replace('.', '', 1).isdigit() and 3 <= float(input_text) <= 10
        if not valid:
            logging.warning(f"❌ Invalid interest rate: {input_text}")
        return valid
    except Exception as e:
        logging.error(f"❌ Interest rate validation error: {str(e)}")
        return False


def validate_remaining_tenure(input_text, user_data=None):
    """Validate remaining tenure (numeric) or allow 'skip'."""
    if input_text.lower() == 'skip':
        return True
    valid = input_text.isdigit() and int(input_text) > 0
    if not valid:
        logging.warning(f"❌ Invalid remaining tenure: {input_text}")
    return valid


def validate_process_completion(input_text, user_data=None):
    """Validation for process completion (always true)."""
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
        'message': "choose_language_message",
        'next_step_map': {
            '1': 'choose_mode',
            '2': 'choose_mode',
            '3': 'choose_mode'
        },
        'next_step': None,
        'validator': lambda x: x in ['1', '2', '3']
    },

    # Step 2: Choose Mode
    'choose_mode': {
        'message': "choose_mode_message",
        'next_step_map': {
            '1': 'get_name',
            '2': 'inquiry_mode'
        },
        'next_step': None,
        'validator': lambda x: x in ['1', '2']
    },

    # Inquiry Mode Activation
    'inquiry_mode': {
        'message': 'inquiry_mode_message',
        'next_step': 'gpt_query_mode',
        'validator': validate_phone_number  # Validate phone number
    },
    
    'gpt_query_mode': {
        'message': 'You may now ask your question!',
        'next_step': None,
     'validator': lambda x: True
    },

    # Savings Estimation Steps
    'get_name': {
        'message': 'name_message',
        'next_step': 'get_phone_number',
        'validator': lambda x: x.replace(' ', '').isalpha()
    },
    'get_phone_number': {
        'message': 'phone_number_message',
        'next_step': 'get_age',
        'validator': lambda x: x.isdigit() and len(x) >= 10
    },
    'get_age': {
        'message': 'age_message',
        'next_step': 'get_loan_amount',
        'validator': lambda x: x.isdigit() and 18 <= int(x) <= 70
    },
    'get_loan_amount': {
        'message': 'loan_amount_message',
        'next_step': 'get_loan_tenure',
        'validator': lambda x: x.replace(',', '').isdigit()
    },
    'get_loan_tenure': {
        'message': 'loan_tenure_message',
        'next_step': 'get_monthly_repayment',
        'validator': lambda x: x.isdigit() and 1 <= int(x) <= 40
    },
    'get_monthly_repayment': {
        'message': 'repayment_message',
        'next_step': 'get_interest_rate',
        'validator': lambda x: x.replace('.', '', 1).isdigit()
    },
    'get_interest_rate': {
        'message': 'interest_rate_message',
        'next_step': 'get_remaining_tenure',
        'validator': lambda x: x.lower() == 'skip' or (x.replace('.', '', 1).isdigit() and 3 <= float(x) <= 10)
    },
    'get_remaining_tenure': {
        'message': 'remaining_tenure_message',
        'next_step': 'process_completion',
        'validator': lambda x: x.lower() == 'skip' or (x.isdigit() and int(x) > 0)
    },
    'process_completion': {
        'message': 'completion_message',
        'next_step': None,
        'validator': lambda x: True
    }
}


# -------------------
# 6) Utility Functions
# -------------------

def get_message(key, language_code, mode='flow'):
    """
    Retrieve a message from the appropriate language file based on language and mode.
    Supports fallback to English for missing messages.
    """
    try:
        # Map numeric language codes to text codes
        LANGUAGE_MAP = {'1': 'en', '2': 'ms', '3': 'zh'}
        language_code = LANGUAGE_MAP.get(language_code, language_code)

        # Retrieve the message key for the mode (flow or inquiry)
        step_key = STEP_CONFIG.get(key, {}).get('message', key)

        # Determine message set based on language
        if language_code not in LANGUAGE_OPTIONS:
            logging.warning(f"⚠️ Language '{language_code}' not found. Defaulting to English.")
            language_code = 'en'

        # Get the message for the step, falling back to English if unavailable
        if mode == 'inquiry':
            message = LANGUAGE_OPTIONS[language_code].get(f"inquiry_{step_key}")
        else:
            message = LANGUAGE_OPTIONS[language_code].get(step_key)

        # Final fallback to default English message if still missing
        if not message:
            message = LANGUAGE_OPTIONS['en'].get(step_key, "Message not available.")
            logging.warning(f"⚠️ Missing key '{step_key}' in '{language_code}'. Using fallback.")

        return message

    except Exception as e:
        logging.error(f"❌ Error in get_message: {str(e)}")
        logging.error(f"Traceback: {traceback.format_exc()}")
        return "Sorry, something went wrong!"


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
        # 1. Handle 'skip' Command Before Validation
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
        # 3. Process Steps with Validation
        # ----------------------------
        step_config = STEP_CONFIG.get(current_step)
        if not step_config:
            logging.error(f"❌ Step configuration not found for step: {current_step}")
            return {"status": "error", "message_key": 'unknown_step'}, 500

        validator = step_config.get('validator')
        if not validator or not validator(message_body):
            logging.warning(f"❌ Validation failed for step: {current_step} with input: {message_body}")
            # Friendly prompt for invalid input
            invalid_msg = get_message('invalid_input_message', user_data.language_code)
            send_messenger_message(messenger_id, invalid_msg)
            return {"status": "failed"}, 200

        # Determine the next step based on whether 'next_step_map' exists
        if 'next_step_map' in step_config:
            next_step = step_config['next_step_map'].get(message_body)
            if not next_step:
                logging.error(f"❌ Invalid input '{message_body}' for step '{current_step}'")
                return {"status": "error", "message": "Invalid step transition"}, 400
        else:
            next_step = step_config.get('next_step')

        # ----------------------------
        # 4. Update User Data Based on Current Step
        # ----------------------------
        if current_step == 'choose_language':
            language_mapping = {'1': 'en', '2': 'ms', '3': 'zh'}
            data_to_update['language_code'] = language_mapping.get(message_body, 'en')

        elif current_step == 'choose_mode':
            if message_body == '1':
                user_data.mode = 'flow'
                next_step = 'get_name'
            elif message_body == '2':
                user_data.mode = 'inquiry'
                next_step = 'inquiry_mode'

        elif current_step == 'get_name':
            data_to_update['name'] = message_body.title()

        elif current_step == 'get_phone_number':
            data_to_update['phone_number'] = str(message_body)

        elif current_step == 'get_age':
            data_to_update['age'] = int(message_body)

        elif current_step == 'get_loan_amount':
            data_to_update['original_loan_amount'] = float(message_body.replace(',', ''))

        elif current_step == 'get_loan_tenure':
            data_to_update['original_loan_tenure'] = int(message_body)

        elif current_step == 'get_monthly_repayment':
            data_to_update['current_repayment'] = float(message_body)

        elif current_step == 'get_interest_rate':
            if message_body.lower() == 'skip':
                data_to_update['interest_rate'] = None
            else:
                data_to_update['interest_rate'] = float(message_body)

        elif current_step == 'get_remaining_tenure':
            if message_body.lower() == 'skip':
                data_to_update['remaining_tenure'] = None
            else:
                data_to_update['remaining_tenure'] = int(message_body)

        elif current_step == 'process_completion':
            return {"status": "success", "next_step": 'process_completion'}, 200

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
        logging.debug(f"🛬 Received raw request data:\n{json.dumps(data, indent=2)}")

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

        # Handle Read/Delivery Receipts
        if 'delivery' in messaging_event or 'read' in messaging_event:
            logging.debug(f"📩 Delivery/Read Receipt received from {sender_id}. Ignored.")
            return jsonify({"status": "ignored"}), 200

        # Extract Text Content
        if 'quick_reply' in message_data:
            message_body = message_data['quick_reply']['payload'].strip().lower()
        elif 'text' in message_data:
            message_body = message_data['text'].strip()
        elif 'payload' in postback_data:
            message_body = postback_data['payload'].strip().lower()
        else:
            logging.warning(f"❌ Unsupported message type from {sender_id}: {message_data}")
            send_messenger_message(sender_id, "Sorry, I can only process text messages for now.")
            return jsonify({"status": "unsupported_message_type"}), 200

        logging.info(f"💎 Incoming message from {sender_id}: {message_body}")

        # ----------------------------
        # 3. Retrieve or Create User Data
        # ----------------------------
        user_data = db.session.query(ChatflowTemp).filter_by(messenger_id=sender_id).first()

        # Create user session if not found
        if not user_data:
            logging.info(f"👤 Creating new session for user {sender_id}")
            user_data = ChatflowTemp(
                sender_id=sender_id,
                messenger_id=messenger_id,
                current_step='choose_language',  # Start with language selection
                language_code='en',
                mode='flow'  # Initial mode remains 'flow'
            )
            db.session.add(user_data)
            db.session.commit()

            # Send welcome message (language selection prompt)
            welcome_message = get_message('choose_language_message', 'en')
            send_messenger_message(sender_id, welcome_message)
            log_chat(sender_id, "New session started", welcome_message, user_data)
            return jsonify({"status": "success"}), 200

        # ----------------------------
        # 4. Restart Flow
        # ----------------------------
        if message_body.lower() in ['restart', 'reset', 'start over']:
            logging.info(f"🔄 Restarting flow for user {sender_id}")
            reset_user_data(user_data, mode='flow')  # Use helper function to reset
            restart_msg = get_message('choose_language_message', 'en')  # Start with language selection
            send_messenger_message(sender_id, restart_msg)
            log_chat(sender_id, message_body, restart_msg, user_data)
            return jsonify({"status": "success"}), 200

        # ----------------------------
        # 5. Handle Inquiry Mode
        # ----------------------------
        if user_data.mode == 'inquiry':
            response = handle_gpt_query(message_body, user_data, sender_id)
            log_chat(sender_id, message_body, response, user_data)
            return jsonify({"status": "success"}), 200

        # ----------------------------
        # 6. Process Inputs
        # ----------------------------
        current_step = user_data.current_step
        process_response, status = process_user_input(current_step, user_data, message_body, messenger_id)

        if status != 200:
            send_messenger_message(sender_id, "Something went wrong. Please restart the process.")
            return jsonify({"status": "error"}), 500

        # Handle next step
        next_step = process_response.get("next_step")
        if next_step:
            # Only assign if next_step is not None
            user_data.current_step = next_step
            db.session.commit()

            # Send the next message
            if next_step != 'process_completion':
                next_message = get_message(next_step, user_data.language_code)
                send_messenger_message(sender_id, next_message)
                log_chat(sender_id, message_body, next_message, user_data)
            else:
                # Process completion step
                send_messenger_message(sender_id, "🎉 Thank you for providing your details. Processing your request now!")
                handle_process_completion(messenger_id)  # Call the completion handler

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
        months_saved = calc_results.get('months_saved', 0)
        years_saved = months_saved // 12  # Calculate full years
        remaining_months = months_saved % 12  # Calculate remaining months

        # Combined Summary (Merges Summary 1 and 2)
        summary_msg = (
            f"📊 Savings Summary:\n\n"
            f"💸 **Current Repayment:** {current_repayment}\n"
            f"💸 **New Repayment:** {new_repayment}\n"
            f"💰 **Monthly Savings:** {monthly_savings}\n"
            f"💰 **Yearly Savings:** {yearly_savings}\n"
            f"🎉 **Lifetime Savings:** {lifetime_savings}\n\n"
            f"⏳ *Equivalent to saving {years_saved} year(s) and {remaining_months} month(s) of repayments!* 🚀"
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

        # Format message with safe defaults and 2 decimal places
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
            f"🕒 **Years Saved:** {calc_results.get('years_saved', 0)} years\n"
            f"📱 **Messenger ID:** {messenger_id}"
        )

        # Send message and log success or error
        send_messenger_message(admin_messenger_id, msg)
        logging.info(f"✅ Lead sent to admin successfully: {admin_messenger_id}")

    except Exception as e:
        logging.error(f"❌ Error sending lead to admin: {str(e)}")

# -------------------
# 9) GPT Query Handling
# -------------------
def handle_gpt_query(question, user_data, messenger_id):
    """Handles GPT queries and saves potential leads in GPTLeads."""

    try:
        # ----------------------------
        # Step 1: Check Preset Responses First
        # ----------------------------
        response = get_preset_response(question, user_data.language_code or 'en')
        if response:
            logging.info(f"✅ Preset response found for query: {question}")
            send_messenger_message(messenger_id, response)
            return response  # Return preset response

        # ----------------------------
        # Step 2: No Preset Found - Use GPT for Refinancing & Mortgage Only
        # ----------------------------
        logging.info(f"❌ No preset match. Querying GPT for: {question}")
        prompt = (
            "You are a mortgage salesperson working for Finzo AI. "
            "Answer questions related to refinancing and mortgage loans only. "
            "Avoid off-topic responses and escalate unrelated queries to an admin. "
            "Be helpful and professional. Focus on generating leads.\n\n"
            f"Question: {question}\nAnswer:"
        )

        # Query GPT for response
        openai_res = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )

        reply = openai_res.choices[0].message.content.strip()
        logging.info(f"✅ GPT response received for user {messenger_id}: {reply}")

        # ----------------------------
        # Step 3: Check If Lead Intent Detected
        # ----------------------------
        lead_prompt = (
            "Analyze the following question to determine if the user is expressing "
            "intent to proceed with refinancing or applying for a loan. "
            "Respond 'YES' for a lead and 'NO' otherwise.\n\n"
            f"Question: {question}\nAnswer:"
        )

        lead_res = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": lead_prompt}]
        )

        lead_decision = lead_res.choices[0].message.content.strip().upper()
        logging.info(f"🔍 GPT lead decision: {lead_decision}")

        # ----------------------------
        # Step 4: If Lead Detected, Collect Details and Save to GPTLeads
        # ----------------------------
        if lead_decision == "YES":
            logging.info(f"🌟 Lead detected for user {messenger_id}")

            # Collect details if missing
            if not user_data.name:
                send_messenger_message(messenger_id, "📝 May I have your full name to proceed?")
                user_data.current_step = 'get_name'  # Ask for name
                db.session.commit()
                return "Awaiting user name."

            if not user_data.phone_number:
                send_messenger_message(messenger_id, "📞 Can I have your phone number for follow-up? (10 digits)")
                user_data.current_step = 'get_phone_number'  # Ask for phone
                db.session.commit()
                return "Awaiting phone number."

            # Save GPT Lead in the new table
            gpt_lead = GPTLead(
                user_id=user_data.id if user_data.name and user_data.phone_number else None,  # Link user if available
                sender_id=user_data.messenger_id,
                name=user_data.name,
                phone_number=user_data.phone_number,
                question=question
            )
            db.session.add(gpt_lead)
            db.session.commit()
            logging.info(f"✅ GPT Lead saved for user {messenger_id}")

            # Notify Admin
            admin_msg = (
                f"📢 **Lead Alert!**\n\n"
                f"👤 **Name:** {user_data.name}\n"
                f"📱 **Phone Number:** {user_data.phone_number}\n"
                f"💬 **Question:** {question}\n\n"
                "📢 Please follow up with this lead."
            )
            admin_id = os.getenv('ADMIN_MESSENGER_ID')
            send_messenger_message(admin_id, admin_msg)

        # ----------------------------
        # Step 5: Send GPT Response to User
        # ----------------------------
        send_messenger_message(messenger_id, reply)
        return reply

    except Exception as e:
        logging.error(f"❌ Error in handle_gpt_query: {str(e)}")
        send_messenger_message(messenger_id, "Sorry, something went wrong. Please try again later.")
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
