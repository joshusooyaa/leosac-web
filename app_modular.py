"""
Main Flask application with modular structure.
"""
import logging
import threading
import time
from flask import Flask
from flask_login import LoginManager
from config.settings import SECRET_KEY
from models.user import LeosacUser
from services.websocket_service import leosac_client
from routes.auth import auth_bp
from routes.users import users_bp
from routes.main import main_bp

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_app():
    """Application factory pattern"""
    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    
    # Flask-Login setup
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    
    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(main_bp)
    
    @login_manager.user_loader
    def load_user(user_id):
        # This function is called by Flask-Login to load a user from the session
        # We need to check if the user is still authenticated with the server
        print(f"load_user called with user_id: {user_id}")
        
        # Check if we have auth info in the session
        from flask import session
        auth_token = session.get('auth_token')
        user_info = session.get('user_info')
        
        print(f"Session auth_token: {bool(auth_token)}")
        print(f"Session user_info: {user_info}")
        
        if user_info and str(user_info.get('user_id')) == user_id and auth_token:
            # Restore the WebSocket client state from session
            leosac_client.set_auth_state(auth_token, user_info)
            
            # Check if the WebSocket client state matches the session
            if (leosac_client.get_auth_state()['auth_token'] == auth_token and 
                leosac_client.get_auth_state()['user_info'] and 
                str(leosac_client.get_auth_state()['user_info'].get('user_id')) == user_id):
                
                # Get the user's rank from the session or default to 'user'
                user_rank = user_info.get('rank', 'user')
                
                user = LeosacUser(
                    user_info['user_id'],
                    user_info['username'],
                    user_rank
                )
                print(f"Returning user: {user.username} with rank: {user.rank}")
                return user
            else:
                print("WebSocket client state mismatch, clearing session")
                # Clear invalid session
                session.pop('auth_token', None)
                session.pop('user_info', None)
                return None
        else:
            print("No valid session found")
        return None
    
    return app

def start_websocket_client():
    """Start WebSocket client in background thread"""
    leosac_client.start()

if __name__ == '__main__':
    logger.info("=== MAIN APPLICATION STARTING ===")
    logger.info(f"Current thread: {threading.current_thread().name}")
    
    # Create Flask app
    app = create_app()
    
    # Start WebSocket client
    logger.info("Starting WebSocket client...")
    start_websocket_client()
    
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
    from config.settings import DEBUG, HOST, PORT
    app.run(debug=DEBUG, host=HOST, port=PORT) 