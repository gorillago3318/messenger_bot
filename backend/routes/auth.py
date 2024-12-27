import os
import logging
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from backend.extensions import db
from ..models import User  # Relative import for models
from ..decorators import user_required, admin_required, agent_required, referrer_required  # Relative import for role-based access

# ✅ Initialize Blueprint with URL prefix
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


@auth_bp.route('/register', methods=['POST'])
def register():
    """
    Registers a new user.
    """
    try:
        data = request.get_json()

        if not data:
            logging.warning("⚠️ Registration request missing required fields.")
            return jsonify({'message': 'Invalid request data.'}), 400

        name = data.get('name')
        email = data.get('email', '').strip().lower()  # Ensure email is lowercase
        password = data.get('password')
        role = data.get('role', 'user').lower()  # Default role is 'user'

        # Validate required fields
        if not all([name, email, password]):
            logging.warning("⚠️ Missing name, email, or password during registration.")
            return jsonify({'message': 'Name, email, and password are required.'}), 400

        if role not in ['user', 'admin', 'agent', 'referrer']:
            logging.warning(f"⚠️ Invalid role provided: {role}")
            return jsonify({'message': 'Invalid role specified. Valid roles: user, admin, agent, referrer.'}), 400

        # Check if user already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            logging.warning(f"⚠️ User with email {email} already exists.")
            return jsonify({'message': 'User with this email already exists.'}), 400

        # Create new user and hash their password
        hashed_password = generate_password_hash(password, method='sha256')
        new_user = User(
            name=name,
            email=email,
            password=hashed_password,
            role=role
        )

        db.session.add(new_user)
        db.session.commit()

        logging.info(f"✅ User {email} registered successfully with role {role}.")
        return jsonify({'message': 'User registered successfully.'}), 201

    except Exception as e:
        logging.error(f"❌ Error during registration: {e}")
        return jsonify({'message': 'An error occurred during registration.'}), 500


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Logs in a user and returns a JWT.
    """
    try:
        data = request.get_json()

        if not data:
            logging.warning("⚠️ Login request missing required fields.")
            return jsonify({'message': 'Invalid request data.'}), 400

        email = data.get('email', '').strip().lower()
        password = data.get('password')

        if not all([email, password]):
            logging.warning("⚠️ Missing email or password during login.")
            return jsonify({'message': 'Email and password are required.'}), 400

        # Find user in the database
        user = User.query.filter_by(email=email).first()
        if not user:
            logging.warning(f"⚠️ Login failed for email {email}: User not found.")
            return jsonify({'message': 'User not found.'}), 404

        # Check password
        if not check_password_hash(user.password, password):
            logging.warning(f"⚠️ Incorrect password for email {email}.")
            return jsonify({'message': 'Incorrect password.'}), 401

        # Create JWT token for user
        access_token = create_access_token(identity=user.id, additional_claims={"role": user.role})
        
        logging.info(f"✅ User {email} logged in successfully.")
        return jsonify({'access_token': access_token}), 200

    except Exception as e:
        logging.error(f"❌ Error during login: {e}")
        return jsonify({'message': 'An error occurred during login.'}), 500


@auth_bp.route('/protected', methods=['GET'])
@jwt_required()
@user_required
def protected():
    """
    A protected route accessible only to users with 'user' role.
    """
    try:
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            logging.warning(f"⚠️ Protected route access failed: User with ID {current_user_id} not found.")
            return jsonify({'message': 'User not found.'}), 404

        logging.info(f"✅ User {user.email} accessed the protected route.")
        return jsonify({'message': f'Hello, {user.name}! This is a protected route.'}), 200

    except Exception as e:
        logging.error(f"❌ Error in protected route: {e}")
        return jsonify({'message': 'An error occurred.'}), 500


# Add more routes as needed, like logout, password reset, etc.
