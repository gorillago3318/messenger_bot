from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from backend.decorators import agent_required  # ✅ Fixed import
from backend.extensions import db  # ✅ Fixed import
from backend.models import Lead  # ✅ Fixed import
import logging

# ✅ Initialize the Blueprint (This was missing)
agent_bp = Blueprint('agent', __name__)

@agent_bp.route('/leads', methods=['GET'])
@jwt_required()
@agent_required
def get_agent_leads():
    """
    Retrieves leads assigned to the agent. Accessible only to agents.
    """
    current_user_id = get_jwt_identity()
    leads = Lead.query.filter_by(referrer_id=current_user_id).all()
    leads_data = []
    for lead in leads:
        leads_data.append({
            'id': lead.id,
            'name': lead.name,
            'age': lead.age,
            'loan_amount': lead.original_loan_amount,  # This was previously incorrect
            'loan_tenure': lead.original_loan_tenure,  # Corrected to match Lead model fields
            'current_repayment': lead.current_repayment,
            'status': lead.status,
            'created_at': lead.created_at,
            'updated_at': lead.updated_at
        })
    return jsonify({'leads': leads_data}), 200

@agent_bp.route('/lead/<int:lead_id>/update', methods=['PUT'])
@jwt_required()
@agent_required
def update_lead_status_agent(lead_id):
    """
    Updates the status of a specific lead. Accessible only to agents.
    """
    data = request.get_json()
    new_status = data.get('status')

    if not new_status:
        return jsonify({'message': 'Status is required.'}), 400

    lead = Lead.query.get(lead_id)
    if not lead:
        return jsonify({'message': 'Lead not found.'}), 404

    current_user_id = get_jwt_identity()
    if lead.referrer_id != current_user_id:
        return jsonify({'message': 'You are not authorized to update this lead.'}), 403

    lead.status = new_status
    db.session.commit()

    return jsonify({'message': 'Lead status updated successfully.'}), 200

# Add more agent routes as needed
