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
        self.translations = {
            'en': {
                'greetings': [
                    "Hey there! 👋 How can I help you with your financial needs today?",
                    "Hello! 😊 Ready to explore your loan options?",
                    "Hi! I'm here to help with all your refinancing questions!",
                    "Welcome! How can I assist you with your home loan today?"
                ],
                'contact_response': "I'll connect you with our team right away: https://wa.me/60126181683",
                'error_message': "I'm having a moment. Please reach out to our team: https://wa.me/60126181683",
                'dynamic_responses': {
                    'refinancing': "Refinancing means replacing your current loan with a new one to get better rates or lower payments. Would you like to know more about the benefits?",
                    'interest_rate': "Our interest rates are competitive and vary based on your loan amount and tenure. Would you like to get a personalized quote?",
                    'documents': "For refinancing, you'll typically need your existing loan details, income documents, and property information. Want me to explain more?",
                    'eligibility': "Loan eligibility depends on factors like income, credit score, and existing commitments. Shall I connect you with our expert for a detailed assessment?"
                }
            },
            'ms': {
                'greetings': [
                    "Hai! 👋 Bagaimana saya boleh bantu keperluan kewangan anda hari ini?",
                    "Hello! 😊 Bersedia untuk meneroka pilihan pinjaman anda?",
                    "Hi! Saya di sini untuk membantu semua soalan pembiayaan semula anda!",
                    "Selamat datang! Bagaimana saya boleh bantu dengan pinjaman rumah anda hari ini?"
                ],
                'contact_response': "Saya akan hubungkan anda dengan pasukan kami sekarang: https://wa.me/60126181683",
                'error_message': "Saya menghadapi masalah. Sila hubungi pasukan kami: https://wa.me/60126181683",
                'dynamic_responses': {
                    'refinancing': "Pembiayaan semula bermaksud menggantikan pinjaman semasa anda dengan yang baru untuk mendapatkan kadar atau bayaran yang lebih baik. Mahu tahu lebih lanjut tentang manfaatnya?",
                    'interest_rate': "Kadar faedah kami kompetitif dan berbeza berdasarkan jumlah dan tempoh pinjaman anda. Mahukah anda mendapatkan sebut harga peribadi?",
                    'documents': "Untuk pembiayaan semula, anda biasanya memerlukan butiran pinjaman sedia ada, dokumen pendapatan, dan maklumat harta. Mahu saya terangkan lebih lanjut?",
                    'eligibility': "Kelayakan pinjaman bergantung pada faktor seperti pendapatan, skor kredit, dan komitmen sedia ada. Boleh saya hubungkan anda dengan pakar kami untuk penilaian terperinci?"
                }
            }
        }

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

    def _get_language(self, user_data):
        """Get user's language code, default to English."""
        return getattr(user_data, 'language_code', 'en')

    def _is_greeting(self, text):
        """Check if the message is a greeting."""
        greetings = ['hi', 'hello', 'hey', 'good morning', 'good afternoon', 'good evening']
        return any(text.lower().startswith(g) for g in greetings)

    def _generate_greeting(self, language_code):
        """Generate greeting in user's language."""
        greetings = self.translations[language_code]['greetings']
        return random.choice(greetings)

    def _handle_contact_queries(self, question, language_code):
        """Handle contact queries in user's language."""
        contact_phrases = [
            "talk to agent", "contact agent", "need help", "speak to someone",
            "talk to human", "contact support", "talk to admin", "reach support",
            "speak to team", "contact admin", "need to speak", "connect me",
            "transfer to agent", "transfer to human", "connect to agent"
        ]
        
        question_lower = question.lower()
        if any(phrase in question_lower for phrase in contact_phrases) or \
           any(word in question_lower.split() for word in ["agent", "human", "admin", "team"]):
            return self.translations[language_code]['contact_response']
        return None

    def _handle_faq_queries(self, question, user_data):
        """Handle FAQ matching with presets."""
        try:
            language_code = getattr(user_data, 'language_code', 'en')
            faq_responses = self.faq_data.get(language_code, {})
            
            normalized_question = self._preprocess_query(question)
            
            if normalized_question in faq_responses:
                return faq_responses[normalized_question]
            
            matches = get_close_matches(normalized_question, faq_responses.keys(), n=1, cutoff=0.7)
            if matches:
                return faq_responses[matches[0]]
            
            return None
            
        except Exception as e:
            logging.error(f"Error in FAQ queries: {str(e)}")
            return None

    def _handle_dynamic_query(self, question, language_code):
        """Handle dynamic responses in user's language."""
        try:
            dynamic_responses = self.translations[language_code]['dynamic_responses']
            question_lower = question.lower()
            
            for key, response in dynamic_responses.items():
                if key in question_lower:
                    return response
            return None
            
        except Exception as e:
            logging.error(f"Error in dynamic query: {str(e)}")
            return None

    def _handle_gpt_query(self, question, language_code):
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
                max_tokens=150
            )
            
            return response['choices'][0]['message']['content'].strip()
            
        except Exception as e:
            logging.error(f"GPT Query Failed: {str(e)}")
            return self.translations[language_code]['error_message']

    def _preprocess_query(self, text):
        """Preprocess user query for better matching."""
        text = re.sub(r'[^\w\s]', '', text.lower())
        return ' '.join(text.split())

    def handle_query(self, question, user_data, messenger_id):
        """Main entry point with language support."""
        try:
            language_code = self._get_language(user_data)
            
            if self._is_greeting(question):
                return self._generate_greeting(language_code)

            contact_response = self._handle_contact_queries(question, language_code)
            if contact_response:
                return contact_response

            faq_response = self._handle_faq_queries(question, user_data)
            if faq_response:
                return faq_response

            dynamic_response = self._handle_dynamic_query(question, language_code)
            if dynamic_response:
                return dynamic_response

            return self._handle_gpt_query(question, language_code)

        except Exception as e:
            logging.error(f"Error in handle_query: {str(e)}")
            return self.translations[self._get_language(user_data)]['error_message']