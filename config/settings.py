"""
Application configuration settings.
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Flask configuration
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Leosac WebSocket configuration
LEOSAC_ADDR = os.environ.get('LEOSAC_ADDR', 'ws://localhost:8888')
WEBSOCKET_URL = f"{LEOSAC_ADDR}/websocket"

# Flask app configuration
DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
HOST = os.environ.get('FLASK_HOST', '0.0.0.0')
PORT = int(os.environ.get('FLASK_PORT', 5000)) 