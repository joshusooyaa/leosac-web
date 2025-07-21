import os
import json
import uuid
import asyncio
import websockets
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
from routes.auth import auth_bp
from models.user import LeosacUser
from werkzeug.security import check_password_hash
from dotenv import load_dotenv
import threading
import time
import logging
import queue
import traceback
import re
from services.websocket_service import leosac_client
from utils.rank_converter import convert_rank_int_to_string, convert_rank_string_to_int, USER_RANKS
from routes.users import users_bp
from routes.credentials import credentials_bp
from routes.schedules import schedules_bp
from routes.groups import groups_bp

# Load environment variables
load_dotenv()

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
app.register_blueprint(auth_bp)
app.register_blueprint(users_bp)
app.register_blueprint(credentials_bp)
app.register_blueprint(schedules_bp)
app.register_blueprint(groups_bp)

# After login_manager is created and initialized, add the user_loader function:
@login_manager.user_loader
def load_user(user_id):
    auth_token = session.get('auth_token')
    user_info = session.get('user_info')
    if user_info and str(user_info.get('user_id')) == user_id and auth_token:
        leosac_client.set_auth_state(auth_token, user_info)
        if (leosac_client.get_auth_state()['auth_token'] == auth_token and 
            leosac_client.get_auth_state()['user_info'] and 
            str(leosac_client.get_auth_state()['user_info'].get('user_id')) == user_id):
            user_rank = user_info.get('rank', 'user')
            user = LeosacUser(
                user_info['user_id'],
                user_info['username'],
                user_rank
            )
            return user
        else:
            session.pop('auth_token', None)
            session.pop('user_info', None)
            return None
    return None

# Configuration
LEOSAC_ADDR = os.environ.get('LEOSAC_ADDR', 'ws://localhost:8888')
WEBSOCKET_URL = f"{LEOSAC_ADDR}/websocket"

logger.info(f"=== LEOSAC WEB APP STARTING ===")
logger.info(f"WebSocket URL: {WEBSOCKET_URL}")
logger.info(f"Current thread: {threading.current_thread().name}")

# Remove @login_manager.user_loader and load_user function from app.py

@app.route('/')
@login_required
def index():
    print(f"Index route accessed by user: {current_user.username if current_user.is_authenticated else 'None'}")
    return render_template('index.html', user=current_user, config={'LEOSAC_ADDR': LEOSAC_ADDR})

@app.route('/login', methods=['GET', 'POST'])
def login():
    logger.info("=== LOGIN ROUTE CALLED ===")
    logger.info(f"Current thread: {threading.current_thread().name}")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Current user authenticated: {current_user.is_authenticated}")

    if current_user.is_authenticated:
        logger.info("User already authenticated, redirecting to index")
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        logger.info(f"Login attempt for username: {username}")
        logger.info(f"WebSocket service ready: {leosac_client._service_ready.is_set()}")
        logger.info(f"WebSocket connected: {leosac_client.connected}")

        if not username or not password:
            logger.warning("Missing username or password")
            flash('Please provide both username and password', 'error')
            return render_template('login.html')

        try:
            logger.info("Calling leosac_client.authenticate...")
            # Use the WebSocket service (thread-safe)
            success, result = leosac_client.authenticate(username, password)

            logger.info(f"Authentication result: success={success}, result={result}")

            if success:
                try:
                    logger.info("Authentication successful, creating user object...")
                    # Get the current auth state
                    auth_state = leosac_client.get_auth_state()
                    
                    # Get user details to get the rank
                    user_details = leosac_client.get_user(auth_state['user_info']['user_id'])
                    user_rank = user_details.get('rank', 'user') if user_details else 'user'
                    
                    user = LeosacUser(
                        auth_state['user_info']['user_id'],
                        auth_state['user_info']['username'],
                        user_rank
                    )
                    logger.info(f"Creating user object: {user.username} (ID: {user.id}) with rank: {user.rank}")
                    logger.info(f"User info before login: {auth_state['user_info']}")
                    logger.info(f"Auth token before login: {auth_state['auth_token']}")
                    
                    # Store authentication info in session
                    session['auth_token'] = auth_state['auth_token']
                    session['user_info'] = {
                        'user_id': auth_state['user_info']['user_id'],
                        'username': auth_state['user_info']['username'],
                        'rank': user_rank
                    }
                    
                    logger.info("About to call login_user...")
                    login_user(user)
                    logger.info("login_user completed successfully")
                    
                    logger.info(f"User authenticated: {current_user.is_authenticated}")
                    logger.info(f"Current user: {current_user.username if current_user.is_authenticated else 'None'}")
                    logger.info(f"Session stored: auth_token={bool(session.get('auth_token'))}, user_info={session.get('user_info')}")
                    
                    flash(f'Welcome {username}!', 'success')
                    logger.info("About to redirect to index...")
                    return redirect(url_for('index'))
                except Exception as e:
                    logger.error(f"Exception in login success block: {e}")
                    logger.error(f"Login success traceback: {traceback.format_exc()}")
                    flash(f'Login error: {str(e)}', 'error')
                    return render_template('login.html')
            else:
                error_msg = result.get("message", result.get("error", "Unknown error"))
                logger.error(f"Authentication failed: {error_msg}")
                flash(f'Authentication failed: {error_msg}', 'error')
        except Exception as e:
            logger.error(f"Authentication exception: {e}")
            logger.error(f"Login route traceback: {traceback.format_exc()}")
            flash(f'Connection error: {str(e)}', 'error')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    print("Logout route called")

    # Use the WebSocket service for logout
    try:
        leosac_client.logout()
        print("WebSocket logout successful")
    except Exception as e:
        print(f"WebSocket logout error: {e}")

    # Clear session data
    session.pop('auth_token', None)
    session.pop('user_info', None)

    # Clear WebSocket client state
    leosac_client.set_auth_state(None, None)

    print("Session and client state cleared")

    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/status')
def status():
    """Check WebSocket connection status"""
    return leosac_client.get_auth_state()

# Overview routes
@app.route('/system-overview')
@login_required
def system_overview():
    return render_template('system_overview.html')

@app.route('/access-overview')
@login_required
def access_overview():
    return render_template('access_overview.html')

@app.route('/zone-overview')
@login_required
def zone_overview():
    return render_template('zone_overview.html')

# Access management routes
@app.route('/groups')
@login_required
def groups_list():
    return render_template('groups/list.html')

@app.route('/groups/create')
@login_required
def groups_create():
    return render_template('groups/create.html')

@app.route('/zones')
@login_required
def zones_list():
    return render_template('zones/list.html')

@app.route('/zones/create')
@login_required
def zones_create():
    return render_template('zones/create.html')

@app.route('/doors')
@login_required
def doors_list():
    return render_template('doors/list.html')

@app.route('/doors/create')
@login_required
def doors_create():
    return render_template('doors/create.html')

@app.route('/access-points')
@login_required
def access_points_list():
    return render_template('access_points/list.html')

@app.route('/access-points/create')
@login_required
def access_points_create():
    return render_template('access_points/create.html')

@app.route('/updates')
@login_required
def updates():
    return render_template('updates.html')

# System routes
@app.route('/auditlog')
@login_required
def auditlog():
    return render_template('auditlog.html')

@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html')

def unique_timeframe_count(timeframes):
    pairs = set()
    for tf in timeframes or []:
        start = tf.get('start_time') if 'start_time' in tf else tf.get('start-time')
        end = tf.get('end_time') if 'end_time' in tf else tf.get('end-time')
        if start is not None and end is not None:
            pairs.add(f"{start}-{end}")
    return len(pairs)

app.jinja_env.filters['unique_timeframe_count'] = unique_timeframe_count

if __name__ == '__main__':
    logger.info("=== MAIN APPLICATION STARTING ===")
    logger.info(f"Current thread: {threading.current_thread().name}")

    # Start WebSocket client
    logger.info("Starting WebSocket client...")
    leosac_client.start()

    # Give some time for initial connection
    logger.info("Waiting 3 seconds for initial connection...")
    time.sleep(3)

    # Check if connection was established
    logger.info("Checking connection status...")
    logger.info(f"Service ready: {leosac_client._service_ready.is_set()}")
    logger.info(f"WebSocket connected: {leosac_client.connected}")
    logger.info(f"WebSocket thread alive: {leosac_client._websocket_thread.is_alive() if leosac_client._websocket_thread else False}")

    if leosac_client.connected:
        logger.info("✓ WebSocket client connected successfully")
    else:
        logger.warning("⚠ WebSocket client not connected, will attempt connection on first request")

    logger.info("Starting Flask app...")
    app.run(debug=True, host='0.0.0.0', port=5000) 