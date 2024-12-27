from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..decorators import agent_required  # Relative import
from backend.extensions import db
from ..models import Lead  # Relative import
import logging

# ✅ Initialize the Blueprint
agent_bp = Blueprint('agent', __name__, url_prefix='/api/agent')

@agent_bp.route('/leads', methods=['GET'])
@jwt_required()
@agent_required
def get_agent_leads():
    """
    Retrieves leads assigned to the agent. Accessible only to agents.
    """
    try:
        current_user_id = get_jwt_identity()
        
        # Fetch only the leads assigned to the current agent
        leads = Lead.query.filter_by(referrer_id=current_user_id).all()
        
        leads_data = []
        for lead in leads:
            leads_data.append({
                'id': lead.id,
                'name': lead.name,
                'age': lead.age,
                'original_loan_amount': lead.original_loan_amount,  # Corrected field name
                'original_loan_tenure': lead.original_loan_tenure,  # Corrected field name
                'current_repayment': lead.current_repayment,
                'status': lead.status,
                'created_at': lead.created_at.strftime('%Y-%m-%d %H:%M:%S') if lead.created_at else None,
                'updated_at': lead.updated_at.strftime('%Y-%m-%d %H:%M:%S') if lead.updated_at else None
            })
        
        logging.info(f"✅ Agent {current_user_id} fetched {len(leads_data)} leads.")
        return jsonify({'leads': leads_data}), 200

    except Exception as e:
        logging.error(f"❌ Error fetching agent leads: {e}")
        return jsonify({'error': 'An error occurred while retrieving leads.'}), 500


@agent_bp.route('/lead/<int:lead_id>/update', methods=['PUT'])
@jwt_required()
@agent_required
def update_lead_status_agent(lead_id):
    """
    Updates the status of a specific lead. Accessible only to agents.
    """
    try:
        data = request.get_json()
        new_status = data.get('status')

        if not new_status:
            logging.warning("⚠️ No status provided for lead update.")
            return jsonify({'message': 'Status is required.'}), 400

        # Get the lead with the specified ID
        lead = Lead.query.get(lead_id)
        if not lead:
            logging.warning(f"⚠️ Lead with ID {lead_id} not found.")
            return jsonify({'message': 'Lead not found.'}), 404

        current_user_id = get_jwt_identity()
        
        # Ensure the agent can only update leads assigned to them
        if lead.referrer_id != current_user_id:
            logging.warning(f"❌ Unauthorized attempt by Agent {current_user_id} to update Lead {lead_id}.")
            return jsonify({'message': 'You are not authorized to update this lead.'}), 403

        # Update the status and commit the change
        lead.status = new_status
        db.session.commit()
        
        logging.info(f"✅ Lead {lead_id} status updated successfully by Agent {current_user_id}.")
        return jsonify({'message': 'Lead status updated successfully.'}), 200

    except Exception as e:
        logging.error(f"❌ Error updating lead status: {e}")
        return jsonify({'error': 'An error occurred while updating the lead status.'}), 500


# Add more agent routes as needed
