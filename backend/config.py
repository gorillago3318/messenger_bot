import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Base configuration class with default settings."""
    # Secret key for application security
    SECRET_KEY = os.getenv('SECRET_KEY')
    if not SECRET_KEY:
        logging.error("❌ SECRET_KEY is missing in .env. Application may be insecure!")
        raise ValueError("SECRET_KEY is required in environment variables.")

    # Database configuration
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    if not SQLALCHEMY_DATABASE_URI:
        logging.error("❌ DATABASE_URL is missing in .env. Application cannot connect to the database!")
        raise ValueError("DATABASE_URL is required in environment variables.")

    # Fix Heroku's 'postgres://' scheme for compatibility with SQLAlchemy
    if SQLALCHEMY_DATABASE_URI.startswith('postgres://'):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace('postgres://', 'postgresql://', 1)

    SQLALCHEMY_TRACK_MODIFICATIONS = False  # Disable SQLAlchemy event tracking for performance

    # General configurations
    DEBUG = os.getenv('DEBUG', 'False').lower() in ['true', '1', 'yes']  # Convert DEBUG to boolean
    ENV = os.getenv('FLASK_ENV', 'development')  # Set the environment (development/production/testing)


class DevelopmentConfig(Config):
    """Configuration for development environment."""
    DEBUG = True
    ENV = 'development'


class ProductionConfig(Config):
    """Configuration for production environment."""
    DEBUG = False
    ENV = 'production'


class TestingConfig(Config):
    """Configuration for testing environment."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'  # Use an in-memory database for tests


# Dictionary to select configuration by environment
configurations = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig
}

# Select the configuration based on environment
current_env = os.getenv('FLASK_ENV', 'development')
config_class = configurations.get(current_env, DevelopmentConfig)

# Log the environment being used
logging.info(f"✅ App running in {config_class.ENV} mode.")
logging.info(f"🗄️ Using database: {config_class.SQLALCHEMY_DATABASE_URI}")
