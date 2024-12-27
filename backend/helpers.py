import logging
from backend.extensions import db
from backend.models import Lead


def get_or_create_lead(phone_number):
    """
    Retrieve an existing lead by phone number or create a new one if it doesn't exist.
    """
    try:
        # Attempt to get the lead
        lead = Lead.query.filter_by(phone_number=phone_number).first()
        
        if not lead:
            logging.info(f"No lead found for phone number {phone_number}. Creating a new lead.")
            lead = Lead(phone_number=phone_number, state='start')
            db.session.add(lead)
            db.session.commit()
            logging.info(f"New lead created for phone number {phone_number}.")
        
        return lead
    except Exception as e:
        logging.error(f"Error in get_or_create_lead for phone number {phone_number}: {e}")
        return None


def get_lead(phone_number):
    """
    Retrieve a lead by phone number.
    """
    try:
        lead = Lead.query.filter_by(phone_number=phone_number).first()
        
        if not lead:
            logging.warning(f"No lead found for phone number {phone_number}")
        
        return lead
    except Exception as e:
        logging.error(f"Error retrieving lead for phone number {phone_number}: {e}")
        return None


def update_lead_state(lead, new_state):
    """
    Update the state of the lead and save it to the database.
    """
    if not lead:
        logging.error(f"Cannot update state because 'lead' is None.")
        return
    
    try:
        lead.state = new_state
        db.session.commit()
        logging.info(f"Lead with phone number {getattr(lead, 'phone_number', 'Unknown')} updated to state '{new_state}'.")
    except Exception as e:
        logging.error(f"Failed to update lead state for phone number {getattr(lead, 'phone_number', 'Unknown')}: {e}")


def reset_lead_state(phone_number):
    """
    Reset the state of the lead for the given phone number.
    """
    try:
        lead = get_lead(phone_number)
        
        if lead:
            lead.state = 'start'  # Reset to start state or None if you prefer
            db.session.commit()
            logging.info(f"Lead state reset for phone number {phone_number}.")
        else:
            logging.warning(f"No lead found to reset for phone number {phone_number}.")
    except Exception as e:
        logging.error(f"Failed to reset lead state for phone number {phone_number}: {e}")
