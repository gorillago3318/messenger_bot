import json
import os
import logging
from difflib import get_close_matches  # Used for fuzzy matching

# Load the preset responses from presets.json
def load_presets():
    """
    Load the presets from presets.json.
    Returns:
        dict: The loaded presets, or an empty dict if the file is missing or invalid.
    """
    try:
        # Get the absolute path to the presets.json file
        base_dir = os.path.dirname(os.path.abspath(__file__))  # Directory of the current file
        presets_path = os.path.join(base_dir, 'presets.json')  # Presets are in the same folder as this file
        
        logging.info(f"🔍 Looking for presets.json at: {presets_path}")
        
        with open(presets_path, 'r', encoding='utf-8') as f:
            logging.info("✅ Successfully loaded presets.json")
            return json.load(f)
    except FileNotFoundError:
        logging.error(f"❌ presets.json file not found at path: {presets_path}")
    except json.JSONDecodeError as e:
        logging.error(f"❌ Invalid JSON format in presets.json: {e}")
    except Exception as e:
        logging.error(f"❌ Unexpected error loading presets.json: {e}")
    return {}

# Global variable to store the presets
PRESETS = load_presets()

def reload_presets():
    """
    Reloads the presets from presets.json without restarting the server.
    """
    global PRESETS
    PRESETS = load_presets()
    logging.info("🔄 Presets reloaded successfully.")

def clean_question(question):
    """
    Cleans the user question by removing extra spaces, punctuation, and special characters.
    Args:
        question (str): The raw user question.
    Returns:
        str: A cleaned, normalized question.
    """
    import re
    question = question.lower().strip()
    question = re.sub(r'[^a-zA-Z0-9\s]', '', question)  # Remove special characters
    question = re.sub(r'\s+', ' ', question)  # Replace multiple spaces with a single space
    return question

def get_preset_response(question, language_code='en'):
    """
    Get a preset response for a given question.
    Args:
        question (str): The user's question.
        language_code (str): The language code (en, ms, zh).
    Returns:
        str: The preset response if it exists, otherwise None.
    """
    try:
        # Normalize the language code (make it lowercase)
        language_code = language_code.lower().strip()
        
        # Get the relevant language's presets
        language_presets = PRESETS.get(language_code, {})
        
        # Clean and normalize the user's question
        cleaned_question = clean_question(question)
        
        # Check for an exact match first
        if cleaned_question in language_presets:
            logging.info(f"✅ Exact match found for question '{cleaned_question}' in {language_code}.")
            return language_presets.get(cleaned_question)
        
        # If exact match not found, use fuzzy matching to find the closest match
        possible_matches = get_close_matches(cleaned_question, language_presets.keys(), n=1, cutoff=0.8)
        if possible_matches:
            best_match = possible_matches[0]
            logging.info(f"🔍 Fuzzy match found: '{cleaned_question}' matched with '{best_match}' in {language_code}.")
            return language_presets.get(best_match)
        
        logging.info(f"❌ No preset response found for question '{cleaned_question}' in {language_code}.")
        return None

    except Exception as e:
        logging.error(f"❌ Error while fetching preset response: {e}")
        return None
