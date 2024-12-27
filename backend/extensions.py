from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()  # ✅ Single instance of db
migrate = Migrate()  # ✅ Single instance of migrate
