# backend/extensions.py

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

# Initialize extensions without binding to the app

db = SQLAlchemy()
migrate = Migrate()