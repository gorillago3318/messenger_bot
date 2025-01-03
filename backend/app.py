import os
import logging
from flask import Flask, request, send_from_directory
from dotenv import load_dotenv
from backend.extensions import db, migrate
from backend.routes.chatbot import chatbot_bp  # Import chatbot route
import requests  # For Messenger API

# Import required models only
from backend.models import User, Lead, BankRate  # Removed ChatflowTemp and ChatLog

# Configure logging
logging.basicConfig(level=logging.INFO)

# Load environment variables
load_dotenv()


def create_app(environ=None, start_response=None):
    """Create and configure the Flask app."""
    app = Flask(__name__, static_folder='../static')  # Point to static folder correctly

    # Setup database config
    database_url = os.getenv('DATABASE_URL', 'sqlite:///local.db')

    # Fix Heroku postgres URL if required
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg2://", 1)

    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize database and migrate
    db.init_app(app)
    migrate.init_app(app, db)

    # Register chatbot routes
    app.register_blueprint(chatbot_bp, url_prefix='/chatbot')

    # Serve index.html at the root URL ("/")
    @app.route('/')
    def home():
        return send_from_directory('../static', 'index.html')  # Adjust path for index.html

    # Webhook setup and routing
    @app.route('/webhook', methods=['GET', 'POST'])
    def webhook():
        if request.method == 'GET':  # Webhook verification
            mode = request.args.get('hub.mode')
            token = request.args.get('hub.verify_token')
            challenge = request.args.get('hub.challenge')

            # Verify token for Messenger
            if mode == 'subscribe' and token == os.getenv('VERIFY_TOKEN'):
                logging.info('✅ Facebook Webhook verification successful!')
                return challenge, 200
            else:
                logging.warning('⚠️ Facebook Webhook verification failed!')
                return 'Verification failed', 403

        elif request.method == 'POST':  # Forward incoming messages to chatbot
            try:
                # Pass incoming request data directly to chatbot.py for processing
                from backend.routes.chatbot import process_message
                return process_message()  # Use chatbot logic directly
            except Exception as e:
                logging.exception(f"❌ Error processing webhook: {e}")
                return 'ERROR', 500

    return app


if __name__ == '__main__':
    app = create_app()
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
