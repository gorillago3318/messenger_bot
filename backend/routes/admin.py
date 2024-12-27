# backend/routes/admin.py

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..decorators import admin_required  # Relative import
from backend.extensions import db
from ..models import Lead, User  # Relative import

import logging

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

@admin_bp.route('/leads', methods=['GET'])
@jwt_required()
@admin_required
def get_all_leads():
    """
    Retrieves all leads. Accessible only to admins.
    """
    try:
        leads = Lead.query.all()
        leads_data = []
        for lead in leads:
            leads_data.append({
                'id': lead.id,
                'phone_number': lead.phone_number,  # Assuming phone number is a key field
                'user_id': lead.user_id,
                'property_reference': lead.property_reference,
                'original_loan_amount': lead.original_loan_amount,
                'original_loan_tenure': lead.original_loan_tenure,
                'current_repayment': lead.current_repayment,
                'new_repayment': lead.new_repayment,
                'monthly_savings': lead.monthly_savings,
                'yearly_savings': lead.yearly_savings,
                'total_savings': lead.total_savings,
                'years_saved': lead.years_saved,
                'interest_rate': lead.interest_rate,
                'remaining_tenure': lead.remaining_tenure,
                'created_at': lead.created_at,
                'updated_at': lead.updated_at
            })
        return jsonify({'leads': leads_data}), 200
    except Exception as e:
        logging.error(f"❌ Error occurred while fetching leads: {e}")
        return jsonify({'message': 'An error occurred while fetching leads.'}), 500


@admin_bp.route('/lead/<int:lead_id>', methods=['PUT'])
@jwt_required()
@admin_required
def update_lead_status(lead_id):
    """
    Updates the status of a specific lead. Accessible only to admins.
    """
    try:
        data = request.get_json()
        new_status = data.get('status')

        if not new_status:
            return jsonify({'message': 'Status is required.'}), 400

        lead = Lead.query.get(lead_id)
        if not lead:
            return jsonify({'message': 'Lead not found.'}), 404

        lead.status = new_status
        db.session.commit()

        return jsonify({'message': 'Lead status updated successfully.'}), 200
    except Exception as e:
        logging.error(f"❌ Error occurred while updating lead status: {e}")
        return jsonify({'message': 'An error occurred while updating lead status.'}), 500

# Add more admin routes as needed
