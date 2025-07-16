import os
import json
import uuid
import asyncio
import websockets
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from dotenv import load_dotenv
import threading
import time
import logging
import queue
import traceback

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

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Configuration
LEOSAC_ADDR = os.environ.get('LEOSAC_ADDR', 'ws://localhost:8888')
WEBSOCKET_URL = f"{LEOSAC_ADDR}/websocket"

logger.info(f"=== LEOSAC WEB APP STARTING ===")
logger.info(f"WebSocket URL: {WEBSOCKET_URL}")
logger.info(f"Current thread: {threading.current_thread().name}")

class LeosacUser(UserMixin):
  def __init__(self, user_id, username, rank=None):
    self.id = user_id
    self.username = username
    self.rank = rank
  
  def get_id(self):
    return str(self.id)
  
  def is_authenticated(self):
    return True
  
  def is_active(self):
    return True
  
  def is_anonymous(self):
    return False

class LeosacWebSocketService:
  """Thread-safe WebSocket service for Flask with extensive debugging"""
  
  def __init__(self):
    logger.info("=== INITIALIZING WEBSOCKET SERVICE ===")
    self.websocket = None
    self.connected = False
    self.callbacks = {}
    self.before_open = []
    self.auth_token = None
    self.user_info = None
    self._lock = threading.Lock()
    self._message_queue = queue.Queue()
    self._websocket_thread = None
    self._running = False
    self._main_loop = None
    self._service_ready = threading.Event()
    logger.info("WebSocket service initialized")
  
  def start(self):
    """Start the WebSocket service in a dedicated thread"""
    logger.info("=== STARTING WEBSOCKET SERVICE ===")
    logger.info(f"Current thread: {threading.current_thread().name}")
    logger.info(f"Service already running: {self._running}")
    logger.info(f"WebSocket thread alive: {self._websocket_thread.is_alive() if self._websocket_thread else False}")
    
    if self._websocket_thread and self._websocket_thread.is_alive():
      logger.info("WebSocket service already running")
      return
    
    self._running = True
    self._websocket_thread = threading.Thread(target=self._websocket_worker, daemon=True, name="WebSocket-Worker")
    self._websocket_thread.start()
    
    # Wait for service to be ready
    logger.info("Waiting for WebSocket service to be ready...")
    if self._service_ready.wait(timeout=10):
      logger.info("✓ WebSocket service started successfully")
    else:
      logger.error("✗ WebSocket service failed to start within 10 seconds")
  
  def stop(self):
    """Stop the WebSocket service"""
    logger.info("=== STOPPING WEBSOCKET SERVICE ===")
    self._running = False
    if self._websocket_thread:
      self._websocket_thread.join(timeout=5)
  
  def _websocket_worker(self):
    """Worker thread that manages the WebSocket connection"""
    logger.info("=== WEBSOCKET WORKER THREAD STARTED ===")
    logger.info(f"Worker thread: {threading.current_thread().name}")
    
    try:
      self._main_loop = asyncio.new_event_loop()
      asyncio.set_event_loop(self._main_loop)
      logger.info("Event loop created and set")
      
      # Signal that the service is ready
      self._service_ready.set()
      
      self._main_loop.run_until_complete(self._websocket_main_loop())
    except Exception as e:
      logger.error(f"WebSocket worker error: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
    finally:
      logger.info("WebSocket worker thread ending")
      if self._main_loop:
        self._main_loop.close()
  
  async def _websocket_main_loop(self):
    """Main WebSocket loop with extensive debugging"""
    logger.info("=== WEBSOCKET MAIN LOOP STARTED ===")
    
    while self._running:
      try:
        if not self.connected:
          logger.info("Not connected, attempting to connect...")
          await self._connect()
        
        if self.connected:
          await self._process_messages()
          await self._process_message_queue()
        
        await asyncio.sleep(0.1)
        
      except Exception as e:
        logger.error(f"WebSocket main loop error: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        self.connected = False
        if self.websocket:
          try:
            await self.websocket.close()
          except:
            pass
          self.websocket = None
        
        logger.info("Waiting 5 seconds before reconnecting...")
        await asyncio.sleep(5)
  
  async def _connect(self):
    """Connect to WebSocket server with debugging"""
    logger.info(f"=== ATTEMPTING CONNECTION TO {WEBSOCKET_URL} ===")
    
    try:
      logger.info("Creating WebSocket connection...")
      self.websocket = await websockets.connect(
        WEBSOCKET_URL,
        ping_interval=30,
        ping_timeout=10,
        close_timeout=10
      )
      self.connected = True
      logger.info("✓ WebSocket connected successfully")
      
      if self.before_open:
        logger.info(f"Processing {len(self.before_open)} queued messages")
        for message in self.before_open:
          await self.websocket.send(json.dumps(message))
        self.before_open.clear()
        logger.info("Queued messages processed")
        
    except Exception as e:
      logger.error(f"✗ Failed to connect: {e}")
      logger.error(f"Connection traceback: {traceback.format_exc()}")
      self.connected = False
      self.websocket = None
  
  async def _process_messages(self):
    """Process incoming WebSocket messages"""
    try:
      message = await asyncio.wait_for(self.websocket.recv(), timeout=0.1)
      logger.debug(f"Received message: {message[:100]}...")
      await self._handle_message(message)
    except asyncio.TimeoutError:
      pass  # No message received
    except websockets.exceptions.ConnectionClosed:
      logger.warning("WebSocket connection closed")
      self.connected = False
      self.websocket = None
    except Exception as e:
      logger.error(f"Error processing message: {e}")
  
  async def _process_message_queue(self):
    """Process messages from the queue"""
    try:
      processed = 0
      while not self._message_queue.empty():
        message_data = self._message_queue.get_nowait()
        if self.connected and self.websocket:
          await self.websocket.send(json.dumps(message_data['message']))
          processed += 1
        else:
          self.before_open.append(message_data['message'])
      
      if processed > 0:
        logger.debug(f"Processed {processed} queued messages")
        
    except queue.Empty:
      pass
    except Exception as e:
      logger.error(f"Error processing message queue: {e}")
  
  async def _handle_message(self, message):
    """Handle incoming WebSocket message"""
    try:
      data = json.loads(message)
      message_uuid = data.get('uuid')
      
      logger.debug(f"Handling message: {data.get('type')} (UUID: {message_uuid})")
      
      if message_uuid in self.callbacks:
        callback_data = self.callbacks[message_uuid]
        result_queue = callback_data.get('result_queue')
        
        if result_queue:
          if data.get('status_code') == 0:
            logger.debug(f"Success for {message_uuid}")
            result_queue.put(data.get('content', {}))
          else:
            logger.debug(f"Error for {message_uuid}: {data.get('status_string')}")
            result_queue.put(None)  # Signal error
        del self.callbacks[message_uuid]
      else:
        if data.get('type') == 'session_closed':
          logger.info(f"Session closed: {data.get('content', {}).get('reason', 'Unknown reason')}")
          with self._lock:
            self.auth_token = None
            self.user_info = None
    except json.JSONDecodeError as e:
      logger.error(f"Failed to parse message: {e}")
  
  def send_json(self, command, content):
    """Send JSON message to Leosac server (thread-safe)"""
    logger.debug(f"=== SENDING JSON: {command} ===")
    logger.debug(f"Current thread: {threading.current_thread().name}")
    logger.debug(f"Service ready: {self._service_ready.is_set()}")
    logger.debug(f"Main loop exists: {self._main_loop is not None}")
    
    message_uuid = str(uuid.uuid4())
    message = {
      'uuid': message_uuid,
      'type': command,
      'content': content
    }
    
    logger.debug(f"Created message with UUID: {message_uuid}")
    
    # Create a result queue to wait for the response
    result_queue = queue.Queue()
    
    # Store the callback and queue
    self.callbacks[message_uuid] = {
      'result_queue': result_queue,
      'message': message
    }
    
    # Queue the message
    self._message_queue.put({
      'message': message,
      'uuid': message_uuid
    })
    
    logger.debug(f"Message queued for {command}")
    
    # Wait for the result
    try:
      result = result_queue.get(timeout=15)  # 15 second timeout
      logger.debug(f"Got result for {command}: {result is not None}")
      return result
    except queue.Empty:
      logger.error(f"Timeout waiting for response to {command}")
      # Clean up the callback
      if message_uuid in self.callbacks:
        del self.callbacks[message_uuid]
      raise Exception(f"Timeout waiting for response to {command}")
  
  def _run_in_websocket_thread(self, command, content):
    """Send a message and wait for response (thread-safe)"""
    logger.debug(f"=== RUNNING IN WEBSOCKET THREAD: {command} ===")
    logger.debug(f"Current thread: {threading.current_thread().name}")
    logger.debug(f"Main loop exists: {self._main_loop is not None}")
    logger.debug(f"Service ready: {self._service_ready.is_set()}")
    
    if not self._main_loop:
      error_msg = "WebSocket service not started - main loop is None"
      logger.error(error_msg)
      raise Exception(error_msg)
    
    if not self._service_ready.is_set():
      error_msg = "WebSocket service not ready"
      logger.error(error_msg)
      raise Exception(error_msg)
    
    try:
      logger.debug(f"Sending {command} via send_json")
      result = self.send_json(command, content)
      logger.debug(f"send_json completed: {result is not None}")
      return result
    except Exception as e:
      logger.error(f"Error in _run_in_websocket_thread: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      raise
  
  def authenticate(self, username, password):
    """Authenticate with username and password (thread-safe)"""
    logger.info(f"=== AUTHENTICATING USER: {username} ===")
    logger.info(f"Current thread: {threading.current_thread().name}")
    
    try:
      logger.debug("Running authentication in websocket thread")
      result = self._run_in_websocket_thread('create_auth_token', {
        'username': username,
        'password': password
      })
      
      logger.debug(f"Authentication result: {result is not None}")
      
      if result:
        with self._lock:
          self.auth_token = result.get('token')
          self.user_info = {
            'user_id': result.get('user_id'),
            'username': username
          }
        logger.info(f"✓ Authentication successful for {username}")
        return True, result
      else:
        logger.warning(f"✗ Authentication failed for {username}")
        return False, {'error': 'Authentication failed'}
        
    except Exception as e:
      logger.error(f"✗ Authentication error for {username}: {e}")
      logger.error(f"Authentication traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}
  
  def authenticate_with_token(self, token):
    """Authenticate with stored token (thread-safe)"""
    logger.info("=== AUTHENTICATING WITH TOKEN ===")
    try:
      result = self._run_in_websocket_thread('authenticate_with_token', {
        'token': token
      })
      
      if result:
        with self._lock:
          self.auth_token = token
          self.user_info = {
            'user_id': result.get('user_id'),
            'username': result.get('username')
          }
        logger.info("✓ Token authentication successful")
        return True, result
      else:
        logger.warning("✗ Token authentication failed")
        return False, {'error': 'Token authentication failed'}
    except Exception as e:
      logger.error(f"✗ Token authentication error: {e}")
      return False, {'error': str(e)}
  
  def logout(self):
    """Logout from Leosac server (thread-safe)"""
    logger.info("=== LOGOUT ===")
    try:
      self._run_in_websocket_thread('logout', {})
      
      with self._lock:
        self.auth_token = None
        self.user_info = None
      logger.info("✓ Logout successful")
      return True
    except Exception as e:
      logger.error(f"✗ Logout error: {e}")
      return False
  
  def get_auth_state(self):
    """Get current authentication state (thread-safe)"""
    with self._lock:
      state = {
        'connected': self.connected,
        'auth_token': self.auth_token,
        'user_info': self.user_info
      }
      logger.debug(f"Auth state: {state}")
      return state
  
  def set_auth_state(self, auth_token, user_info):
    """Set authentication state (thread-safe)"""
    with self._lock:
      self.auth_token = auth_token
      self.user_info = user_info
    logger.debug(f"Auth state set: token={bool(auth_token)}, user={user_info}")
  
  def get_users(self):
    """Get all users (thread-safe)"""
    logger.info("=== GETTING USERS ===")
    try:
      result = self._run_in_websocket_thread('user.read', {'user_id': 0})
      
      if result and 'data' in result:
        users = []
        for user_data in result['data']:
          user = {
            'id': user_data.get('id'),
            **user_data.get('attributes', {})
          }
          users.append(user)
        logger.info(f"✓ Retrieved {len(users)} users")
        return users
      logger.warning("✗ No users data in response")
      return []
    except Exception as e:
      logger.error(f"✗ Error getting users: {e}")
      return []
  
  def get_user(self, user_id):
    """Get a specific user by ID (thread-safe)"""
    logger.info(f"=== GETTING USER: {user_id} ===")
    try:
      result = self._run_in_websocket_thread('user.read', {'user_id': int(user_id)})
      
      if result and 'data' in result:
        user_data = result['data']
        if isinstance(user_data, list):
          if len(user_data) > 0:
            user_data = user_data[0]
          else:
            logger.warning(f"✗ User {user_id} not found (empty list)")
            return None
        
        user = {
          'id': user_data.get('id'),
          **user_data.get('attributes', {})
        }
        logger.info(f"✓ Retrieved user {user_id}")
        return user
      logger.warning(f"✗ User {user_id} not found")
      return None
    except Exception as e:
      logger.error(f"✗ Error getting user {user_id}: {e}")
      return None
  
  def create_user(self, user_data):
    """Create a new user (thread-safe)"""
    logger.info(f"=== CREATING USER: {user_data.get('username')} ===")
    try:
      result = self._run_in_websocket_thread('user.create', {
        'attributes': user_data
      })
      
      success = result is not None
      logger.info(f"{'✓' if success else '✗'} User creation {'successful' if success else 'failed'}")
      return success, result
    except Exception as e:
      logger.error(f"✗ Error creating user: {e}")
      return False, {'error': str(e)}
  
  def update_user(self, user_id, user_data):
    """Update an existing user (thread-safe)"""
    logger.info(f"=== UPDATING USER: {user_id} ===")
    try:
      result = self._run_in_websocket_thread('user.update', {
        'user_id': int(user_id),
        'attributes': user_data
      })
      
      success = result is not None
      logger.info(f"{'✓' if success else '✗'} User update {'successful' if success else 'failed'}")
      return success, result
    except Exception as e:
      logger.error(f"✗ Error updating user {user_id}: {e}")
      return False, {'error': str(e)}
  
  def delete_user(self, user_id):
    """Delete a user (thread-safe)"""
    logger.info(f"=== DELETING USER: {user_id} ===")
    try:
      result = self._run_in_websocket_thread('user.delete', {
        'user_id': int(user_id)
      })
      
      success = result is not None
      logger.info(f"{'✓' if success else '✗'} User deletion {'successful' if success else 'failed'}")
      return success, result
    except Exception as e:
      logger.error(f"✗ Error deleting user {user_id}: {e}")
      return False, {'error': str(e)}

# Global WebSocket client
leosac_client = LeosacWebSocketService()

# Start the websocket client in a background thread
def start_websocket_client():
    """Start WebSocket client in background thread (following Ember pattern)"""
    leosac_client.start()

# Start the websocket client at import time
start_websocket_client()

@login_manager.user_loader
def load_user(user_id):
    # This function is called by Flask-Login to load a user from the session
    # We need to check if the user is still authenticated with the server
    print(f"load_user called with user_id: {user_id}")
    
    # Check if we have auth info in the session
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
            
            user = LeosacUser(
                user_info['user_id'],
                user_info['username']
            )
            print(f"Returning user: {user.username}")
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
                    user = LeosacUser(
                        auth_state['user_info']['user_id'],
                        auth_state['user_info']['username']
                    )
                    logger.info(f"Creating user object: {user.username} (ID: {user.id})")
                    logger.info(f"User info before login: {auth_state['user_info']}")
                    logger.info(f"Auth token before login: {auth_state['auth_token']}")
                    
                    # Store authentication info in session
                    session['auth_token'] = auth_state['auth_token']
                    session['user_info'] = auth_state['user_info']
                    
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
@app.route('/users')
@login_required
def users_list():
    """List all users"""
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            logger.warning('WebSocket connection not available in users_list route.')
            flash('WebSocket connection not available. Please try again.', 'error')
            return render_template('users/list.html', users=[])
        users = leosac_client.get_users()
        return render_template('users/list.html', users=users)
    except Exception as e:
        logger.error(f'Error loading users: {str(e)}')
        flash(f'Error loading users: {str(e)}', 'error')
        return render_template('users/list.html', users=[])

@app.route('/users/create', methods=['GET', 'POST'])
@login_required
def users_create():
    """Create a new user"""
    if request.method == 'POST':
        try:
            # Check if WebSocket client is connected
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return render_template('users/create.html', user_data=request.form, ranks=['admin', 'user'])
            
            # Get form data
            user_data = {
                'username': request.form.get('username'),
                'firstname': request.form.get('firstname'),
                'lastname': request.form.get('lastname'),
                'email': request.form.get('email'),
                'password': request.form.get('password'),
                'rank': request.form.get('rank', 'user')
            }
            
            # Validate required fields
            if not all([user_data['username'], user_data['firstname'], 
                       user_data['lastname'], user_data['email'], user_data['password']]):
                flash('All fields are required', 'error')
                return render_template('users/create.html', user_data=user_data, ranks=['admin', 'user'])
            
            # Create user via WebSocket
            success, result = leosac_client.create_user(user_data)
            
            if success:
                flash('User created successfully!', 'success')
                return redirect(url_for('users_list'))
            else:
                error_msg = result.get('status_string', 'Unknown error')
                flash(f'Failed to create user: {error_msg}', 'error')
                return render_template('users/create.html', user_data=user_data)
                
        except Exception as e:
            flash(f'Error creating user: {str(e)}', 'error')
            return render_template('users/create.html', user_data=request.form, ranks=['admin', 'user'])
    
    # Available user ranks
    ranks = ['admin', 'user']
    return render_template('users/create.html', ranks=ranks)

@app.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
def users_delete(user_id):
    """Delete a user"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('users_list'))
        
        # Don't allow deleting the current user
        if user_id == current_user.id:
            flash('You cannot delete your own account', 'error')
            return redirect(url_for('users_list'))
        
        # Delete user via WebSocket
        success, result = leosac_client.delete_user(user_id)
        
        if success:
            flash('User deleted successfully!', 'success')
        else:
            error_msg = result.get('status_string', 'Unknown error')
            flash(f'Failed to delete user: {error_msg}', 'error')
            
    except Exception as e:
        flash(f'Error deleting user: {str(e)}', 'error')
    
    return redirect(url_for('users_list'))

@app.route('/groups')
@login_required
def groups_list():
    return render_template('groups/list.html')

@app.route('/groups/create')
@login_required
def groups_create():
    return render_template('groups/create.html')

@app.route('/credentials')
@login_required
def credentials_list():
    return render_template('credentials/list.html')

@app.route('/credentials/rfid/create')
@login_required
def credentials_rfid_create():
    return render_template('credentials/rfid_create.html')

@app.route('/credentials/pin/create')
@login_required
def credentials_pin_create():
    return render_template('credentials/pin_create.html')

@app.route('/schedules')
@login_required
def schedules_list():
    return render_template('schedules/list.html')

@app.route('/schedules/create')
@login_required
def schedules_create():
    return render_template('schedules/create.html')

# Hardware management routes
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

@app.route('/profile/<int:user_id>')
@login_required
def profile(user_id):
    """View user profile"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('users_list'))
        
        # Get user details from WebSocket
        user = leosac_client.get_user(user_id)
        
        if user:
            return render_template('profile.html', user=user)
        else:
            flash('User not found', 'error')
            return redirect(url_for('users_list'))
            
    except Exception as e:
        flash(f'Error loading user profile: {str(e)}', 'error')
        return redirect(url_for('users_list'))

@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html')

if __name__ == '__main__':
    logger.info("=== MAIN APPLICATION STARTING ===")
    logger.info(f"Current thread: {threading.current_thread().name}")
    
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
    app.run(debug=True, host='0.0.0.0', port=5000) 