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
# Support multiple addresses via LEOSAC_ADDRS (comma-separated). Fallback to LEOSAC_ADDR.
LEOSAC_ADDR = os.environ.get('LEOSAC_ADDR', 'ws://localhost:8888')
LEOSAC_ADDRS = os.environ.get('LEOSAC_ADDRS')

if LEOSAC_ADDRS:
  addrs = [addr.strip() for addr in LEOSAC_ADDRS.split(',') if addr.strip()]
else:
  addrs = [LEOSAC_ADDR]

# Backward-compatible single URL and a list of URLs
WEBSOCKET_URL = f"{addrs[0]}/websocket"
WEBSOCKET_URLS = [f"{addr}/websocket" for addr in addrs]

# Flask app configuration
DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
HOST = os.environ.get('FLASK_HOST', '0.0.0.0')
PORT = int(os.environ.get('FLASK_PORT', 5000)) 