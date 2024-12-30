import re
import random
import logging
import json
import os
from datetime import datetime
from difflib import get_close_matches
import openai

class ChatbotHandler:
    def __init__(self):
        self.faq_data = self._load_faq_data()
    
    def _load_faq_data(self):
        """Load FAQ data from presets.json in utils folder."""
        try:
            preset_path = os.path.join(os.path.dirname(__file__), 'presets.json')
            with open(preset_path, 'r') as file:
                presets_data = json.load(file)
            return presets_data.get('faq', {})
        except Exception as e:
            logging.error(f"Error loading FAQ data: {str(e)}")
            return {}

    def handle_query(self, question, user_data, messenger_id):
        """Main entry point for handling user queries."""
        try:
            # First check for greetings
            if self._is_greeting(question):
                return self._generate_greeting()

            # Check FAQ matches
            faq_response = self._handle_faq_queries(question, user_data)
            if faq_response:
                return faq_response

            # Check for contact requests
            contact_response = self._handle_contact_queries(question)
            if contact_response:
                return contact_response

            # Try keywords/dynamic responses
            dynamic_response = self._handle_dynamic_query(question, user_data)
            if dynamic_response:
                return dynamic_response

            # Fallback to GPT
            return self._handle_gpt_query(question)

        except Exception as e:
            logging.error(f"Error in handle_query: {str(e)}")
            return "I'm having a moment. Please reach out to our team: https://wa.me/60126181683"

    def _is_greeting(self, text):
        """Check if the message is a greeting."""
        greetings = ['hi', 'hello', 'hey', 'good morning', 'good afternoon', 'good evening']
        return any(text.lower().startswith(g) for g in greetings)

    def _generate_greeting(self):
        """Generate a friendly greeting response."""
        greetings = [
            "Hey there! 👋 How can I help you with your financial needs today?",
            "Hello! 😊 Ready to explore your loan options?",
            "Hi! I'm here to help with all your refinancing questions!",
            "Welcome! How can I assist you with your home loan today?"
        ]
        return random.choice(greetings)

    def _handle_faq_queries(self, question, user_data):
        """Handle FAQ matching with presets."""
        try:
            language_code = getattr(user_data, 'language_code', 'en')
            faq_responses = self.faq_data.get(language_code, {})
            
            normalized_question = self._preprocess_query(question)
            
            # Direct match
            if normalized_question in faq_responses:
                return faq_responses[normalized_question]
            
            # Fuzzy match
            matches = get_close_matches(normalized_question, faq_responses.keys(), n=1, cutoff=0.7)
            if matches:
                return faq_responses[matches[0]]
            
            return None
            
        except Exception as e:
            logging.error(f"Error in FAQ queries: {str(e)}")
            return None

    def _handle_contact_queries(self, question):
        """Handle contact-related queries."""
        contact_phrases = [
            "talk to agent", "contact agent", "need help", "speak to someone",
            "talk to human", "contact support", "talk to admin", "reach support"
        ]
        if any(phrase in question.lower() for phrase in contact_phrases):
            return "I'll connect you with our team right away: https://wa.me/60126181683"
        return None

    def _handle_dynamic_query(self, question, user_data):
        """Handle dynamic keyword-based responses."""
        try:
            keywords = {
                'refinancing': "Refinancing means replacing your current loan with a new one to get better rates or lower payments. Would you like to know more about the benefits?",
                'interest rate': "Our interest rates are competitive and vary based on your loan amount and tenure. Would you like to get a personalized quote?",
                'documents': "For refinancing, you'll typically need your existing loan details, income documents, and property information. Want me to explain more?",
                'eligibility': "Loan eligibility depends on factors like income, credit score, and existing commitments. Shall I connect you with our expert for a detailed assessment?"
            }
            
            # Check for keyword matches
            for key, response in keywords.items():
                if key in question.lower():
                    return response
                    
            return None
            
        except Exception as e:
            logging.error(f"Error in dynamic query: {str(e)}")
            return None

    def _handle_gpt_query(self, question):
        """Handle queries using GPT."""
        try:
            system_prompt = (
                "You are Finzo AI Buddy, a friendly Malaysian financial assistant specializing in home loans "
                "and refinancing. Keep responses concise, helpful, and natural. Focus on providing accurate "
                "information about home loans, refinancing, and related financial topics in Malaysia."
            )
            
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question}
                ],
                temperature=0.7,
                max_tokens=150  # Keep responses concise
            )
            
            return response['choices'][0]['message']['content'].strip()
            
        except Exception as e:
            logging.error(f"GPT Query Failed: {str(e)}")
            return "I'm not quite sure about that. Our team can help better: https://wa.me/60126181683"

    def _preprocess_query(self, text):
        """Preprocess user query for better matching."""
        # Convert to lowercase and remove punctuation
        text = re.sub(r'[^\w\s]', '', text.lower())
        # Remove extra whitespace
        return ' '.join(text.split())