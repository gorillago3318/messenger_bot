# db_test.py

from backend.app import create_app  # Import the app creation function
from backend.extensions import db  # Import the db instance from extensions

# Create the Flask app
app = create_app()  # This initializes the Flask app and connects SQLAlchemy

# Use the app context
with app.app_context():
    print(f"Database URL: {db.engine.url}")  # Print the database URL to verify the connection
