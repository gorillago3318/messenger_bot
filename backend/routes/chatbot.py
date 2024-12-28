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


PROMPTS = {
            'en': {
                'choose_language': "🎉 Welcome to FinZo AI — Your Smart Refinancing Assistant! 🤖\n\n💸 **Discover Your Savings Potential** – Instantly estimate how much you could save by refinancing your home loan.\n💡 **Expert Guidance at Your Fingertips** – Get quick answers to your refinancing and home loan questions (up to 15 inquiries).\n🔄 **Simple Restart** – Need to reset? Just type 'restart' anytime to start over.\n\n👉 Let's get started! Please select your preferred language:\n\n🌐 **Choose Language:**\n1️⃣ *English* \n2️⃣ *Bahasa Malaysia* \n3️⃣ *中文 (Chinese)*",
                'get_name': "📝 *Step 1: Enter Your Name* \n\nPlease enter your *full name* as it appears on official documentation. \n\n💡 *Example*: John Doe",
                'get_phone_number': "📞 *Step 2: Enter Your Phone Number* \n\nPlease enter your *phone number* (minimum 10 digits). \n\n💡 *Example*: 0123456789",
                'get_age': "🎂 *Step 3: Enter Your Age* \n\nPlease enter your *age in years* (must be between *18 and 70*). \n\n💡 *Example*: 35",
                'get_loan_amount': "💸 *Step 4: Enter Your Loan Amount* \n\nPlease enter the *original loan amount* that you initially took from the bank. \n\n💡 *Example*: 250000 (do not use commas or special symbols).",
                'get_loan_tenure': "📆 *Step 5: Enter Your Loan Tenure* \n\nPlease enter your *original loan tenure* approved by the bank. (This is normally 30 or 35 years.) \n\n💡 *Example*: 30.",
                'get_monthly_repayment': "💳 *Step 6: Enter Your Current Monthly Repayment* \n\nPlease enter the *current amount you pay each month* for your loan. \n\n💡 *Example*: 2500 (do not use commas or special symbols).",
                'get_interest_rate': "📈 *Step 7: Enter Your Interest Rate* \n\nIf you know the *current interest rate* for your loan, please enter it (e.g., 3.85). \n\nYou can also type *skip* if you are unsure. \n\n💡 *Example*: 4.25 or *skip*.",
                'get_remaining_tenure': "📅 *Step 8: Enter the Remaining Tenure* \n\nPlease enter the *number of years remaining* for your loan. \n\n💡 *Note*: You can skip this if you don't know the exact number. Just type *skip*. \n\n💡 *Example*: 15 or *skip*.",
                'thank_you': "🎉 Process complete! Thank you for using FinZo AI. You are now in inquiry mode.",           
                'invalid_choose_language': "⚠️ Invalid language selection. Please select 1 for English, 2 for Bahasa Malaysia, or 3 for 中文 (Chinese).",
                'invalid_get_name': "⚠️ Invalid name. Please enter letters only.",
                'invalid_get_phone_number': "⚠️ Invalid phone number. It must start with '01' and be 10–11 digits long. Example: 0123456789.",
                'invalid_get_age': "⚠️ Invalid age. Please enter a valid number between 18 and 70.",
                'invalid_get_loan_amount': "⚠️ Invalid loan amount. Enter numbers only without commas or symbols. Example: 250000.",
                'invalid_get_loan_tenure': "⚠️ Invalid loan tenure. Enter a number between 1 and 40 years. Example: 30.",
                'invalid_get_monthly_repayment': "⚠️ Invalid repayment amount. Enter numbers only without commas or symbols. Example: 2500.",
                'invalid_get_interest_rate': "⚠️ Invalid interest rate. Enter a number between 3% and 10%, or type 'skip' if unsure. Example: 4.25 or 'skip'.",
                'invalid_get_remaining_tenure': "⚠️ Invalid remaining tenure. Enter a number greater than 0 or type 'skip' if unsure. Example: 15 or 'skip'."
            },
            'ms': {
                'choose_language': "🎉 Selamat datang ke FinZo AI — Pembantu Pembiayaan Semula Pintar Anda! 🤖\n\n💸 **Temui Potensi Penjimatan Anda** – Anggarkan dengan segera berapa banyak yang anda boleh jimatkan dengan membiayai semula pinjaman rumah anda.\n💡 **Bimbingan Pakar di Hujung Jari** – Dapatkan jawapan segera untuk soalan pembiayaan semula dan pinjaman rumah anda (sehingga 15 pertanyaan).\n🔄 **Mula Semula dengan Mudah** – Perlu bermula semula? Hanya taip 'restart' pada bila-bila masa.\n\n👉 Mari kita mulakan! Sila pilih bahasa pilihan anda:\n\n🌐 **Pilih Bahasa:**\n1️⃣ *English* \n2️⃣ *Bahasa Malaysia* \n3️⃣ *中文 (Chinese)*",
                'get_name': "📝 *Langkah 1: Masukkan Nama Anda* \n\nSila masukkan *nama penuh* anda seperti yang tertera pada dokumen rasmi. \n\n💡 *Contoh*: Ahmad bin Abdullah",
                'get_phone_number': "📞 *Langkah 2: Masukkan Nombor Telefon Anda* \n\nSila masukkan *nombor telefon* anda (minimum 10 digit). \n\n💡 *Contoh*: 0123456789",
                'get_age': "🎂 *Langkah 3: Masukkan Umur Anda* \n\nSila masukkan *umur anda dalam tahun* (mesti antara *18 dan 70*). \n\n💡 *Contoh*: 35",
                'get_loan_amount': "💸 *Langkah 4: Masukkan Jumlah Pinjaman Anda* \n\nSila masukkan *jumlah pinjaman asal* yang anda ambil dari bank. \n\n💡 *Contoh*: 250000 (jangan gunakan koma atau simbol khas).",
                'get_loan_tenure': "📆 *Langkah 5: Masukkan Tempoh Pinjaman Anda* \n\nSila masukkan *tempoh pinjaman asal* yang diluluskan oleh bank. (Ini biasanya 30 atau 35 tahun.) \n\n💡 *Contoh*: 30.",
                'get_monthly_repayment': "💳 *Langkah 6: Masukkan Bayaran Bulanan Semasa Anda* \n\nSila masukkan *jumlah yang anda bayar setiap bulan* untuk pinjaman anda. \n\n💡 *Contoh*: 2500 (jangan gunakan koma atau simbol khas).",
                'get_interest_rate': "📈 *Langkah 7: Masukkan Kadar Faedah Anda* \n\nJika anda tahu *kadar faedah semasa* untuk pinjaman anda, sila masukkan (contoh: 3.85). \n\nAnda juga boleh taip *skip* jika anda tidak pasti. \n\n💡 *Contoh*: 4.25 atau *skip*.",
                'get_remaining_tenure': "📅 *Langkah 8: Masukkan Baki Tempoh* \n\nSila masukkan *bilangan tahun yang berbaki* untuk pinjaman anda. \n\n💡 *Nota*: Anda boleh langkau jika anda tidak tahu jumlah yang tepat. Hanya taip *skip*. \n\n💡 *Contoh*: 15 atau *skip*.",
                'thank_you': "Proses selesai! Terima kasih kerana menggunakan FinZo AI. Anda kini berada dalam mod pertanyaan.",
                'invalid_choose_language': "⚠️ Pilihan bahasa tidak sah. Sila pilih 1 untuk English, 2 untuk Bahasa Malaysia, atau 3 untuk 中文 (Chinese).",
                'invalid_get_name': "⚠️ Nama tidak sah. Sila masukkan huruf sahaja.",
                'invalid_get_phone_number': "⚠️ Nombor telefon tidak sah. Mesti bermula dengan '01' dan mempunyai 10-11 digit. Contoh: 0123456789.",
                'invalid_get_age': "⚠️ Umur tidak sah. Sila masukkan nombor yang sah antara 18 dan 70.",
                'invalid_get_loan_amount': "⚠️ Jumlah pinjaman tidak sah. Masukkan nombor sahaja tanpa koma atau simbol. Contoh: 250000.",
                'invalid_get_loan_tenure': "⚠️ Tempoh pinjaman tidak sah. Masukkan nombor antara 1 dan 40 tahun. Contoh: 30.",
                'invalid_get_monthly_repayment': "⚠️ Jumlah bayaran tidak sah. Masukkan nombor sahaja tanpa koma atau simbol. Contoh: 2500.",
                'invalid_get_interest_rate': "⚠️ Kadar faedah tidak sah. Masukkan nombor antara 3% dan 10%, atau taip 'skip' jika tidak pasti. Contoh: 4.25 atau 'skip'.",
                'invalid_get_remaining_tenure': "⚠️ Baki tempoh tidak sah. Masukkan nombor lebih besar daripada 0 atau taip 'skip' jika tidak pasti. Contoh: 15 atau 'skip'."
            },
             'zh': {
                'choose_language': "🎉 欢迎使用 FinZo AI — 您的智能再融资助手！🤖\n\n💸 **发现您的储蓄潜力** – 立即估算通过房屋贷款再融资可以节省多少。\n💡 **专业指导触手可及** – 快速获得再融资和房屋贷款问题的答案（最多15个咨询）。\n🔄 **简单重启** – 需要重置？随时输入'restart'即可重新开始。\n\n👉 让我们开始吧！请选择您的首选语言：\n\n🌐 **选择语言：**\n1️⃣ *English* \n2️⃣ *Bahasa Malaysia* \n3️⃣ *中文 (Chinese)*",
                'get_name': "📝 *步骤1：输入姓名* \n\n请输入您的*全名*，需与官方文件上的姓名一致。 \n\n💡 *示例*：张明华",
                'get_phone_number': "📞 *步骤2：输入电话号码* \n\n请输入您的*电话号码*（至少10位数字）。 \n\n💡 *示例*：0123456789",
                'get_age': "🎂 *步骤3：输入年龄* \n\n请输入您的*年龄*（必须在*18至70岁*之间）。 \n\n💡 *示例*：35",
                'get_loan_amount': "💸 *步骤4：输入贷款金额* \n\n请输入您最初从银行获得的*原始贷款金额*。 \n\n💡 *示例*：250000（请勿使用逗号或特殊符号）。",
                'get_loan_tenure': "📆 *步骤5：输入贷款期限* \n\n请输入银行批准的*原始贷款期限*。（通常为30或35年。） \n\n💡 *示例*：30。",
                'get_monthly_repayment': "💳 *步骤6：输入当前每月还款额* \n\n请输入您当前*每月的贷款还款金额*。 \n\n💡 *示例*：2500（请勿使用逗号或特殊符号）。",
                'get_interest_rate': "📈 *步骤7：输入利率* \n\n如果您知道贷款的*当前利率*，请输入（例如：3.85）。 \n\n如果不确定，您也可以输入*skip*。 \n\n💡 *示例*：4.25 或 *skip*。",
                'get_remaining_tenure': "📅 *步骤8：输入剩余期限* \n\n请输入您的贷款*剩余年数*。 \n\n💡 *注意*：如果您不知道确切数字，可以跳过此步骤。只需输入*skip*。 \n\n💡 *示例*：15 或 *skip*。",
                'thank_you': "🎉 流程已完成！感谢您使用 FinZo AI。您现在处于询问模式。", 
                'invalid_choose_language': "⚠️ 语言选择无效。请选择 1 代表英语，2 代表马来语，或 3 代表中文。",
                'invalid_get_name': "⚠️ 姓名无效。请只输入字母。",
                'invalid_get_phone_number': "⚠️ 电话号码无效。必须以'01'开头，并且有10-11位数字。示例：0123456789。",
                'invalid_get_age': "⚠️ 年龄无效。请输入18至70之间的有效数字。",
                'invalid_get_loan_amount': "⚠️ 贷款金额无效。请只输入数字，不要使用逗号或符号。示例：250000。",
                'invalid_get_loan_tenure': "⚠️ 贷款期限无效。请输入1至40年之间的数字。示例：30。",
                'invalid_get_monthly_repayment': "⚠️ 还款金额无效。请只输入数字，不要使用逗号或符号。示例：2500。",
                'invalid_get_interest_rate': "⚠️ 利率无效。请输入3%至10%之间的数字，或如果不确定请输入'skip'。示例：4.25或'skip'。",
                'invalid_get_remaining_tenure': "⚠️ 剩余期限无效。请输入大于0的数字，或如果不确定请输入'skip'。示例：15或'skip'。"
            }
        }

# -------------------
# 2) Initialize OpenAI client
# -------------------
openai.api_key = os.getenv("OPENAI_API_KEY").strip()
logging.debug(f"API Key: {openai.api_key}") # Set it directly or via environment variable

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
        # 1. Initialize Step Mapping
        # ----------------------------
        next_step_mapping = {
            'choose_language': 'get_name',
            'get_name': 'get_phone_number',
            'get_phone_number': 'get_age',
            'get_age': 'get_loan_amount',
            'get_loan_amount': 'get_loan_tenure',
            'get_loan_tenure': 'get_monthly_repayment',
            'get_monthly_repayment': 'get_interest_rate',
            'get_interest_rate': 'get_remaining_tenure',
            'get_remaining_tenure': 'process_completion'  # Triggers calculation and summary
        }

        # ----------------------------
        # 2. Handle 'skip' Command Before Validation
        # ----------------------------
        if message_body.lower() == 'skip':
            logging.info(f"🔄 Skipping input for step: {current_step}")
            next_step = next_step_mapping.get(current_step, None)

            # Update user step and commit changes before sending the next prompt
            user_data.current_step = next_step
            db.session.commit()

            # Fetch and send the next prompt
            language = user_data.language_code if user_data.language_code in PROMPTS else 'en'
            next_prompt = PROMPTS[language].get(next_step, "⚠️ Invalid input. Please check and try again.")
            send_messenger_message(messenger_id, next_prompt)

            return {"status": "success", "next_step": next_step}, 200

        # ----------------------------
        # 3. Input Validation
        # ----------------------------
        def validate_input(step, value):
            if step == 'get_name':
                return value.replace(' ', '').isalpha()
            if step == 'get_phone_number':
                return value.isdigit() and value.startswith('01') and len(value) in [10, 11]
            if step == 'get_age':
                return value.isdigit() and 18 <= int(value) <= 70
            if step == 'get_loan_amount':
                return value.replace(',', '').isdigit()
            if step == 'get_loan_tenure':
                return value.isdigit() and 1 <= int(value) <= 40
            if step == 'get_monthly_repayment':
                return value.replace('.', '', 1).isdigit()
            if step == 'get_interest_rate':
                return value.lower() == 'skip' or (value.replace('.', '', 1).isdigit() and 3 <= float(value) <= 10)
            if step == 'get_remaining_tenure':
                if value.lower() == 'skip':  # Allow skipping
                    return True
                if not value.isdigit():  # Ensure numeric input
                    return False
                remaining = int(value)

                # Refresh user data to ensure latest state
                db.session.refresh(user_data)
                original = user_data.original_loan_tenure

                # Validate if original tenure is None or not set
                if original is None:
                    logging.error("❌ Original loan tenure is missing during validation.")
                    return False

                # Validate remaining tenure cannot exceed original tenure
                if remaining > original or remaining <= 0:
                    return False
                return True
            return True

        # Validate Input
        if not validate_input(current_step, message_body):
            # Show only error message without proceeding to the next step
            language = user_data.language_code if user_data.language_code in PROMPTS else 'en'
            error_msg = PROMPTS[language].get(f"invalid_{current_step}", "⚠️ Invalid input. Please check and try again.")
            send_messenger_message(messenger_id, error_msg)
            return {"status": "failed"}, 200  # Return without moving forward

        # ----------------------------
        # 4. Apply Updates Based on Input
        # ----------------------------
        update_mapping = {
            'get_name': lambda x: {'name': x.title()},
            'get_phone_number': lambda x: {'phone_number': x},
            'get_age': lambda x: {'age': int(x)},
            'get_loan_amount': lambda x: {'original_loan_amount': float(x.replace(',', ''))},
            'get_loan_tenure': lambda x: {'original_loan_tenure': int(x)},
            'get_monthly_repayment': lambda x: {'current_repayment': float(x)},
            'get_interest_rate': lambda x: {'interest_rate': None if x.lower() == 'skip' else float(x)},
            'get_remaining_tenure': lambda x: {'remaining_tenure': None if x.lower() == 'skip' else int(x)}
        }

        # Update user data
        if current_step in update_mapping:
            updates = update_mapping[current_step](message_body)
            for key, value in updates.items():
                setattr(user_data, key, value)

        # Commit updated data
        db.session.commit()

        # ----------------------------
        # 5. Move to the Next Step
        # ----------------------------
        next_step = next_step_mapping.get(current_step, None)

        # Trigger Calculation for Final Step
        if next_step == 'process_completion':
            result = handle_process_completion(messenger_id)

            if result[1] != 200:  # Error during calculation
                send_messenger_message(messenger_id, "⚠️ Error calculating savings. Please restart the process.")
            return {"status": "success"}, 200

        user_data.current_step = next_step
        db.session.commit()
        language = user_data.language_code if user_data.language_code in PROMPTS else 'en'
        next_prompt = PROMPTS[language].get(next_step, "⚠️ Invalid input.")
        send_messenger_message(messenger_id, next_prompt)

        logging.debug(f"🔄 Moved to next step: {next_step}")
        return {"status": "success"}, 200

    except Exception as e:
        logging.error(f"❌ Error in process_user_input: {str(e)}")
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
        message_body = None

        # Handle 'Get Started' Payload
        if 'payload' in postback_data:
            message_body = postback_data['payload'].strip().lower()

            if message_body == 'get_started':
                logging.info(f"🌟 User {sender_id} clicked the 'Get Started' button.")
                # Initialize or reset the user data
                user_data = db.session.query(ChatflowTemp).filter_by(messenger_id=sender_id).first()
                if user_data:
                    reset_user_data(user_data, mode='flow')
                else:
                    user_data = ChatflowTemp(
                        sender_id=sender_id,
                        messenger_id=messenger_id,
                        current_step='choose_language',
                        language_code='en',
                        mode='flow'
                    )
                    db.session.add(user_data)
                    db.session.commit()

                user_data.current_step = 'choose_language'
                db.session.commit()
                send_messenger_message(sender_id, PROMPTS['en']['choose_language'])
                return jsonify({"status": "success"}), 200

        # Handle greeting without "Get Started" payload
        message_body = message_data.get('text', '').strip().lower()
        if message_body in ['hi', 'hello', 'hey', 'greetings', 'good morning', 'good afternoon']:
            logging.info(f"🌟 User {sender_id} greeted with: {message_body}")
            
            # Retrieve or create user data for the first interaction
            user_data = db.session.query(ChatflowTemp).filter_by(messenger_id=sender_id).first()
            if not user_data:
                user_data = ChatflowTemp(
                    sender_id=sender_id,
                    messenger_id=messenger_id,
                    current_step='choose_language',
                    language_code='en',
                    mode='flow'
                )
                db.session.add(user_data)
                db.session.commit()
                user_data.current_step = 'choose_language'
                db.session.commit()

            send_messenger_message(sender_id, "👋 Hello! Let's get started. Please choose your language:\n1️⃣ English\n2️⃣ Bahasa Malaysia\n3️⃣ 中文 (Chinese)")
            return jsonify({"status": "success"}), 200

        # ----------------------------
        # 3. Extract text or quick reply if no greeting
        # ----------------------------
        if not message_body:
            logging.error(f"❌ No valid message found from {sender_id}")
            send_messenger_message(sender_id, "Sorry, I can only process text or button replies for now.")
            return jsonify({"status": "error", "message": "No valid message found"}), 400

        logging.info(f"💎 Incoming message from {sender_id}: {message_body}")

        # ----------------------------
        # 4. Retrieve User Data
        # ----------------------------
        user_data = db.session.query(ChatflowTemp).filter_by(messenger_id=sender_id).first()

        # Handle Reset Commands
        if message_body.lower() in ['restart', 'reset', 'start over']:
            logging.info(f"🔄 Restarting flow for user {sender_id}")
            reset_user_data(user_data, mode='flow')
            user_data.current_step = 'choose_language'
            db.session.commit()
            send_messenger_message(sender_id, PROMPTS['en']['choose_language'])
            return jsonify({"status": "success"}), 200

        # ----------------------------
        # 5. Handle Inquiry Mode
        # ----------------------------
        if user_data.mode == 'inquiry':
            logging.info(f"💬 Inquiry mode for user {sender_id}")
            try:
                response = handle_gpt_query(message_body, user_data, messenger_id)
            except Exception as e:
                logging.error(f"❌ GPT query error: {str(e)}")
                language = user_data.language_code if user_data.language_code in PROMPTS else 'en'
                response = PROMPTS[language].get('inquiry_mode_message', "⚠️ An error occurred. Please try again.")
            log_chat(sender_id, message_body, response, user_data)
            send_messenger_message(sender_id, response)
            return jsonify({"status": "success"}), 200

        # ----------------------------
        # 6. Process Regular Flow
        # ----------------------------
        current_step = user_data.current_step
        process_response, status = process_user_input(current_step, user_data, message_body, messenger_id)

        if status != 200:
            # Handle Invalid Input
            invalid_msg = PROMPTS['en'][f"invalid_{current_step}"]
            send_messenger_message(sender_id, invalid_msg)
            return jsonify({"status": "error"}), 500

        # Move to the Next Step
        next_step = process_response.get("next_step")
        if next_step:
            if user_data.current_step != next_step:  # Prevent duplicate prompts
                user_data.current_step = next_step
                db.session.commit()

                # Handle Final Completion
                if next_step == 'process_completion':
                    send_messenger_message(sender_id, PROMPTS['en']['completion_message'])
                    result = handle_process_completion(messenger_id)
                    if result[1] != 200:
                        send_messenger_message(sender_id, "Sorry, we encountered an error. Please restart.")
                    else:
                        user_data.mode = 'inquiry'
                        db.session.commit()
                        # Don't send the greeting message again here
                    return jsonify({"status": "success"}), 200

                # Send Next Prompt
                language = user_data.language_code if user_data.language_code in PROMPTS else 'en'
                next_message = PROMPTS[language].get(next_step, "⚠️ Invalid input. Please check and try again.")
                send_messenger_message(sender_id, next_message)
                log_chat(sender_id, message_body, next_message, user_data)

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
        current_repayment = round(float(user_data.current_repayment), 2)
        new_repayment = round(float(results.get('new_monthly_repayment', 0.0)), 2)
        monthly_savings = round(float(results.get('monthly_savings', 0.0)), 2)
        yearly_savings = round(float(results.get('yearly_savings', 0.0)), 2)
        lifetime_savings = round(float(results.get('lifetime_savings', 0.0)), 2)
        years_saved = results.get('years_saved', 0)
        months_saved = results.get('months_saved', 0)

        logging.debug(f"💰 Savings - Monthly: {monthly_savings} RM, New Repayment: {new_repayment} RM, "
                      f"Current Repayment: {current_repayment} RM")

        # ----------------------------
        # Handle Case Where New Repayment is Higher or No Savings
        # ----------------------------
        if new_repayment >= current_repayment:
            # Fetch WhatsApp link from environment variable or fallback
            whatsapp_link = os.getenv('ADMIN_WHATSAPP_LINK', "https://wa.me/60167177813")

            msg = (
                "Thank you for using FinZo AI! Based on your details, your **current repayment** is already optimal, "
                "and refinancing may not provide immediate savings.\n\n"
                f"💬 Need assistance? Contact our admin directly via WhatsApp: {whatsapp_link}"
            )
            send_messenger_message(messenger_id, msg)

            # Switch to inquiry mode
            user_data.mode = 'inquiry'
            db.session.commit()
            logging.info(f"✅ No savings case handled. User switched to inquiry mode.")
            return jsonify({"status": "success"}), 200

        # ----------------------------
        # Step 5: Generate and send summary messages
        # ----------------------------
        summary_messages = prepare_summary_messages(user_data, results, user_data.language_code or 'en')
        for m in summary_messages:
            try:
                send_messenger_message(messenger_id, m)
            except Exception as e:
                logging.error(f"❌ Failed to send summary message to {messenger_id}: {str(e)}")

        # Step 6: Notify admin about the new lead
        try:
            send_new_lead_to_admin(messenger_id, user_data, results)
        except Exception as e:
            logging.error(f"❌ Failed to notify admin: {str(e)}")

        # Step 7: Save results in the database
        try:
            update_database(messenger_id, user_data, results)
        except Exception as e:
            logging.error(f"❌ Failed to save results in database: {str(e)}")

        # Step 8: Switch to inquiry mode with language-specific greeting
        user_data.mode = 'inquiry'
        db.session.commit()

        # Fetch WhatsApp link from environment variable
        whatsapp_link = os.getenv('ADMIN_WHATSAPP_LINK', "https://wa.me/60167177813")

        # Inquiry Mode Greeting based on user language
        language = user_data.language_code if user_data.language_code in PROMPTS else 'en'
        inquiry_greetings = {
            'en': (
                "🎉 *Welcome to Inquiry Mode!* 🎉\n\n"
                "🤖 *FinZo AI Assistant* is now activated. Ask me anything about *home refinancing* or *housing loans*.\n\n"
                "💬 *You can ask about loan eligibility, refinancing steps, or required documents.*\n\n"
                f"📱 Need urgent help? Contact admin via WhatsApp: {whatsapp_link}"
            ),
            'ms': (
                "🎉 *Selamat datang ke Mod Pertanyaan!* 🎉\n\n"
                "🤖 *Pembantu AI FinZo* kini diaktifkan. Tanyakan apa sahaja tentang *pembiayaan semula rumah* atau *pinjaman perumahan*.\n\n"
                "💬 *Anda boleh bertanya tentang kelayakan pinjaman, langkah pembiayaan semula, atau dokumen yang diperlukan.*\n\n"
                f"📱 Perlukan bantuan segera? Hubungi admin melalui WhatsApp: {whatsapp_link}"
            ),
            'zh': (
                "🎉 *欢迎进入咨询模式!* 🎉\n\n"
                "🤖 *FinZo AI 助手* 现在已启动。您可以询问关于 *房屋再融资* 或 *住房贷款* 的任何问题。\n\n"
                "💬 *您可以询问贷款资格、再融资步骤或所需文件。*\n\n"
                f"📱 如需帮助，请通过 WhatsApp 联系管理员: {whatsapp_link}"
            )
        }

        # Send the appropriate inquiry greeting based on the user's language
        inquiry_greeting = inquiry_greetings.get(language, inquiry_greetings['en'])
        send_messenger_message(messenger_id, inquiry_greeting)

        logging.info(f"✅ Process completed successfully for {messenger_id}. Switched to inquiry mode with greeting.")

        return jsonify({"status": "success"}), 200

    except Exception as e:
        # Error handling
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
        # Step 1: Check if the user is in inquiry mode
        if user_data.mode != 'inquiry':
            logging.info(f"🚫 User {messenger_id} is not in inquiry mode. Ignoring GPT query.")
            return "Please complete the process before asking questions."

        # Step 2: Fetch preset response first
        response = get_preset_response(question, user_data.language_code or 'en')
        if response:
            logging.info(f"✅ Preset response found for query: {question}")
            return response  # Only return the preset response if found

        # ----------------------------
        # Step 3: Query GPT if no preset response is found
        # ----------------------------

        # Map language code to full names for GPT instruction
        language_map = {
            'en': 'English',
            'ms': 'Malay',
            'zh': 'Chinese'
        }

        # Determine preferred language
        preferred_language = language_map.get(user_data.language_code, 'English')

        # Construct GPT system prompt with language preference and topic focus
        logging.info(f"❌ No preset match. Querying GPT in {preferred_language} for: {question}")
        system_prompt = (
            f"You are a helpful assistant for home refinancing and home loan queries. "
            f"Your responses should strictly be about home loans, mortgages, refinancing, interest rates, and related financial topics. "
            f"Please respond in {preferred_language}."
        )

        # Making GPT request to ensure it sticks to the right topic (home loans and refinancing)
        openai_res = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ]
        )

        # Extract GPT response
        reply = openai_res['choices'][0]['message']['content'].strip()
        logging.info(f"✅ GPT response received for user {messenger_id}: {reply}")

        # Log GPT query and response
        log_gpt_query(messenger_id, question, reply)

        # Return GPT response
        return reply

    except Exception as e:
        # Log error and return a fallback message
        logging.error(f"❌ Error in handle_gpt_query: {str(e)}")
        return "Sorry, something went wrong! Please try again or contact support."


def log_gpt_query(messenger_id, question, response):
    """Logs GPT queries to ChatLog."""
    try:
        messenger_id = str(messenger_id)
        user = User.query.filter_by(messenger_id=messenger_id).first()

        # Create or update user with default values if missing
        if not user:
            user = User(
                messenger_id=messenger_id,
                name="Unknown User",
                age=0,
                phone_number="Unknown"  # Default value
            )
            db.session.add(user)
            db.session.flush()  # Flush to get user ID

        # Handle missing details if user exists
        user.name = user.name or "Unknown User"
        user.age = user.age or 0
        user.phone_number = user.phone_number or "Unknown"

        # Log the GPT query in ChatLog
        chat_log = ChatLog(
            user_id=user.id,
            message_content=f"User (GPT Query): {question}\nBot: {response}",
            phone_number=user.phone_number  # Ensure phone number is set
        )
        db.session.add(chat_log)
        db.session.commit()
        logging.info(f"✅ GPT query logged for user {user.messenger_id}")

    except Exception as e:
        # Log error and rollback
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
