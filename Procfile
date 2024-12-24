release: flask db upgrade
web: gunicorn --preload --worker-class=sync --bind 0.0.0.0:5000 backend.app:create_app
