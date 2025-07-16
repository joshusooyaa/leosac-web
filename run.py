#!/usr/bin/env python3
"""
Startup script for Leosac Web GUI Flask application
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Check if LEOSAC_ADDR is set
if not os.environ.get('LEOSAC_ADDR'):
    print("Warning: LEOSAC_ADDR environment variable not set.")
    print("Using default: ws://localhost:8888")
    print("Set LEOSAC_ADDR in your .env file or environment to connect to your Leosac server.")
    print()

# Import and run the Flask app
from app import app

if __name__ == '__main__':
    print("Starting Leosac Web GUI Flask Application...")
    print(f"Leosac Server: {os.environ.get('LEOSAC_ADDR', 'ws://localhost:8888')}")
    print("Web Interface: http://localhost:5000")
    print("Press Ctrl+C to stop")
    print()
    
    app.run(debug=True, host='0.0.0.0', port=5000) 