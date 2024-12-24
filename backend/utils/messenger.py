import os
import requests
import logging

FACEBOOK_API_URL = os.getenv("FACEBOOK_API_URL")
FACEBOOK_API_TOKEN = os.getenv("FACEBOOK_API_TOKEN")

def send_messenger_message(recipient_id, text):
    """Send a text message using the Facebook Messenger API."""
    url = f"{FACEBOOK_API_URL}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {FACEBOOK_API_TOKEN}"
    }
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        logging.info(f"✅ Message sent to {recipient_id}: {text}")
    except Exception as e:
        logging.error(f"❌ Failed to send message: {e}")
