import os
import requests
import logging

# Load required environment variables
FACEBOOK_API_URL = "https://graph.facebook.com/v21.0/me/messages"
FACEBOOK_API_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")  # Correct Token Variable

def send_messenger_message(recipient_id, text):
    """Send a text message using the Facebook Messenger API."""
    # Construct API endpoint with Access Token in URL
    url = f"{FACEBOOK_API_URL}?access_token={FACEBOOK_API_TOKEN}"
    headers = {
        "Content-Type": "application/json"
    }

    # Ensure recipient_id is string-encoded
    recipient_id = str(recipient_id)

    # Create JSON payload
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }

    try:
        # Send POST request
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # Raise exception for HTTP errors
        
        # Log success
        logging.info(f"✅ Message sent to {recipient_id}: {text}")
        logging.info(f"Response: {response.json()}")  # Log API response for debugging

    except requests.exceptions.RequestException as e:
        # Capture errors
        logging.error(f"❌ Failed to send message: {e}")
        if response is not None:  # Log the response content for debugging
            logging.error(f"Response: {response.text}")
