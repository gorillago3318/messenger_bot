# backend/decorators.py

from functools import wraps
from flask import jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt

def user_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        claims = get_jwt()
        if 'role' in claims and claims['role'] == 'user':
            return fn(*args, **kwargs)
        else:
            return jsonify(msg='User access required'), 403
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        claims = get_jwt()
        if 'role' in claims and claims['role'] == 'admin':
            return fn(*args, **kwargs)
        else:
            return jsonify(msg='Admin access required'), 403
    return wrapper

def agent_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        claims = get_jwt()
        if 'role' in claims and claims['role'] == 'agent':
            return fn(*args, **kwargs)
        else:
            return jsonify(msg='Agent access required'), 403
    return wrapper

def referrer_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        claims = get_jwt()
        if 'role' in claims and claims['role'] == 'referrer':
            return fn(*args, **kwargs)
        else:
            return jsonify(msg='Referrer access required'), 403
    return wrapper
