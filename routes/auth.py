"""
Authentication routes for Flask application.
"""
import logging
import traceback
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user, login_manager
from models.user import LeosacUser
from services.websocket_service import leosac_client

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

# Remove the @login_manager.user_loader and load_user function from this file

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    logger.info("=== LOGIN ROUTE CALLED ===")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Current user authenticated: {current_user.is_authenticated}")
    
    if current_user.is_authenticated:
        logger.info("User already authenticated, redirecting to index")
        return redirect(url_for('index'))
    
    # If all servers are down, show a banner on the splash screen
    try:
        st = leosac_client.get_auth_state() or {}
        health = st.get('server_health') or {}
        servers = st.get('server_urls') or []
        if servers and all((not (health.get(s) or {}).get('up', False)) for s in servers):
            flash('All Leosac servers appear to be down. Login is currently unavailable.', 'error')
    except Exception:
        pass

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
                    
                    # Resolve user id/username
                    user_id = (auth_state.get('user_info') or {}).get('user_id')
                    username_from_state = (auth_state.get('user_info') or {}).get('username') or username
                    # make a change here
                    # Get user details to get the rank (if we have an id)
                    user_rank = 'user'
                    if user_id is not None:
                        try:
                            user_details = leosac_client.get_user(user_id)
                            user_rank = user_details.get('rank', 'user') if user_details else 'user'
                        except Exception:
                            user_rank = 'user'
                    
                    user = LeosacUser(
                        user_id,
                        username_from_state,
                        user_rank
                    )
                    logger.info(f"Creating user object: {user.username} (ID: {user.id}) with rank: {user.rank}")
                    logger.info(f"User info before login: {auth_state['user_info']}")
                    logger.info(f"Auth token before login: {auth_state['auth_token']}")
                    
                    # Store authentication info in session
                    session['auth_token'] = auth_state.get('auth_token')
                    session['user_info'] = {
                        'user_id': user_id,
                        'username': username_from_state,
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

@auth_bp.route('/logout')
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
    return redirect(url_for('auth.login')) 