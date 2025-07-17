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
import re

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

# User ranks matching Ember implementation
USER_RANKS = ['user', 'viewer', 'manager', 'supervisor', 'administrator']

def convert_rank_int_to_string(rank_int):
    """Convert rank integer to string (matching Ember user-rank transform)"""
    rank_mapping = {
        0: 'user',
        1: 'viewer',
        2: 'manager',
        3: 'supervisor',
        4: 'administrator'
    }
    return rank_mapping.get(rank_int, 'user')

def convert_rank_string_to_int(rank_string):
    """Convert rank string to integer (matching Ember user-rank transform)"""
    rank_mapping = {
        'user': 0,
        'viewer': 1,
        'manager': 2,
        'supervisor': 3,
        'administrator': 4
    }
    return rank_mapping.get(rank_string, 0)

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
            # For successful responses, return content if available, otherwise return a success indicator
            content = data.get('content')
            if content is not None:
              result_queue.put(content)
            else:
              # For empty content (like updates), return a success indicator
              result_queue.put({'success': True, 'status_code': 0})
          else:
            logger.debug(f"Error for {message_uuid}: {data.get('status_string')}")
            # Put the error details instead of None
            error_response = {
              'status_code': data.get('status_code'),
              'status_string': data.get('status_string', 'Unknown error')
            }
            result_queue.put(error_response)
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
        logger.debug(f"Raw user data from server: {result['data'][:2]}")  # Log first 2 users for debugging
        users = []
        for user_data in result['data']:
          # Convert rank integer to string
          rank_int = user_data.get('attributes', {}).get('rank', 0)
          rank_string = convert_rank_int_to_string(rank_int)
          
          logger.debug(f"User {user_data.get('id')}: rank_int={rank_int}, rank_string={rank_string}")
          
          user = {
            'id': user_data.get('id'),
            'username': user_data.get('attributes', {}).get('username'),
            'firstname': user_data.get('attributes', {}).get('firstname'),
            'lastname': user_data.get('attributes', {}).get('lastname'),
            'email': user_data.get('attributes', {}).get('email'),
            'rank': rank_string,
            'validity_enabled': user_data.get('attributes', {}).get('validity-enabled', False),  # Handle hyphens from server
            'validity_start': user_data.get('attributes', {}).get('validity-start'),  # Handle hyphens from server
            'validity_end': user_data.get('attributes', {}).get('validity-end'),  # Handle hyphens from server
            'version': user_data.get('attributes', {}).get('version', 0),
            # Include relationship data that's already in the response
            'relationships': user_data.get('relationships', {})
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
        
        # Convert rank integer to string
        rank_int = user_data.get('attributes', {}).get('rank', 0)
        rank_string = convert_rank_int_to_string(rank_int)
        
        user = {
          'id': user_data.get('id'),
          'username': user_data.get('attributes', {}).get('username'),
          'firstname': user_data.get('attributes', {}).get('firstname'),
          'lastname': user_data.get('attributes', {}).get('lastname'),
          'email': user_data.get('attributes', {}).get('email'),
          'rank': rank_string,
          'validity_enabled': user_data.get('attributes', {}).get('validity-enabled', False),  # Handle hyphens from server
          'validity_start': user_data.get('attributes', {}).get('validity-start'),  # Handle hyphens from server
          'validity_end': user_data.get('attributes', {}).get('validity-end'),  # Handle hyphens from server
          'version': user_data.get('attributes', {}).get('version', 0),
          # Include relationship data that's already in the response
          'relationships': user_data.get('relationships', {})
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
      # Convert rank string to integer for server
      if 'rank' in user_data:
        user_data['rank'] = convert_rank_string_to_int(user_data['rank'])
      
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
      # Convert rank string to integer for server
      if 'rank' in user_data:
        user_data['rank'] = convert_rank_string_to_int(user_data['rank'])
      
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

  def get_user_groups(self, user_id):
    """Get user's group memberships (thread-safe)"""
    logger.info(f"=== GETTING USER GROUPS: {user_id} ===")
    try:
      result = self._run_in_websocket_thread('user-group-membership.read', {'user_id': int(user_id)})
      
      if result and 'data' in result:
        memberships = []
        for membership_data in result['data']:
          # Convert group rank integer to string
          group_rank_int = membership_data.get('attributes', {}).get('rank', 0)
          group_rank_string = 'administrator' if group_rank_int == 2 else 'operator' if group_rank_int == 1 else 'member'
          
          membership = {
            'id': membership_data.get('id'),
            'user_id': membership_data.get('attributes', {}).get('user_id'),
            'group_id': membership_data.get('attributes', {}).get('group_id'),
            'rank': group_rank_string,
            'timestamp': membership_data.get('attributes', {}).get('timestamp'),
            'group': membership_data.get('relationships', {}).get('group', {}).get('data', {})
          }
          memberships.append(membership)
        logger.info(f"✓ Retrieved {len(memberships)} group memberships for user {user_id}")
        return memberships
      logger.warning(f"✗ No group memberships found for user {user_id}")
      return []
    except Exception as e:
      logger.error(f"✗ Error getting user groups for {user_id}: {e}")
      return []

  def get_user_credentials(self, user_id):
    """Get user's credentials (thread-safe)"""
    logger.info(f"=== GETTING USER CREDENTIALS: {user_id} ===")
    try:
      # Get all credentials and filter by owner_id on client side
      # The server doesn't support filtering by owner_id in credential.read
      result = self._run_in_websocket_thread('credential.read', {'credential_id': 0})
      
      logger.debug(f"Raw credential result for user {user_id}: {result}")

      if result and 'data' in result:
        credentials = []
        logger.debug(f"Processing {len(result['data'])} total credentials, filtering for user {user_id}")
        
        for cred_data in result['data']:
          logger.debug(f"Processing credential: {cred_data}")
          
          # Check if this credential belongs to the user
          owner_id = None
          if cred_data.get('relationships', {}).get('owner', {}).get('data', {}).get('id'):
            owner_id = cred_data.get('relationships', {}).get('owner', {}).get('data', {}).get('id')
          
          logger.debug(f"Credential {cred_data.get('id')} owner_id: {owner_id}, looking for user_id: {user_id}")
          
          # Only include credentials owned by this user
          if str(owner_id) == str(user_id):
            credential = {
              'id': cred_data.get('id'),
              'alias': cred_data.get('attributes', {}).get('alias'),
              'description': cred_data.get('attributes', {}).get('description'),
              'type': cred_data.get('type'),
              'validity_enabled': cred_data.get('attributes', {}).get('validity-enabled', False),  # Handle hyphens from server
              'validity_start': cred_data.get('attributes', {}).get('validity-start'),  # Handle hyphens from server
              'validity_end': cred_data.get('attributes', {}).get('validity-end'),  # Handle hyphens from server
              'version': cred_data.get('attributes', {}).get('version', 0)
            }
            
            # Add RFID-specific fields
            if cred_data.get('type') == 'rfid-card':
              card_id = cred_data.get('attributes', {}).get('card-id')  # Handle hyphens from server
              nb_bits = cred_data.get('attributes', {}).get('nb-bits')  # Handle hyphens from server
              credential.update({
                'card_id': card_id,
                'nb_bits': nb_bits,
                'display_identifier': card_id
              })
            elif cred_data.get('type') == 'pin-code':
              credential.update({
                'code': cred_data.get('attributes', {}).get('code'),
                'display_identifier': '***' + cred_data.get('attributes', {}).get('code', '')[-4:] if cred_data.get('attributes', {}).get('code') else 'N/A'
              })
            
            credentials.append(credential)
            logger.debug(f"Added credential for user {user_id}: {credential}")
          else:
            logger.debug(f"Skipping credential {cred_data.get('id')} - not owned by user {user_id}")
        
        logger.info(f"✓ Retrieved {len(credentials)} credentials for user {user_id}")
        return credentials
      else:
        logger.warning(f"✗ No credentials found for user {user_id} - result: {result}")
        return []
    except Exception as e:
      logger.error(f"✗ Error getting user credentials for {user_id}: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return []

  def get_user_schedules(self, user_id):
    """Get user's schedule mappings (thread-safe)"""
    logger.info(f"=== GETTING USER SCHEDULES: {user_id} ===")
    try:
      result = self._run_in_websocket_thread('schedule-mapping.read', {'user_id': int(user_id)})

      if result and 'data' in result:
        schedules = []
        for schedule_data in result['data']:
          schedule = {
            'id': schedule_data.get('id'),
            'alias': schedule_data.get('attributes', {}).get('alias'),
            'schedule_id': schedule_data.get('relationships', {}).get('schedule', {}).get('data', {}).get('id'),
            'schedule_name': schedule_data.get('relationships', {}).get('schedule', {}).get('data', {}).get('attributes', {}).get('name', 'Unknown'),
            'version': schedule_data.get('attributes', {}).get('version', 0)
          }
          schedules.append(schedule)
        logger.info(f"✓ Retrieved {len(schedules)} schedule mappings for user {user_id}")
        return schedules
      logger.warning(f"✗ No schedule mappings found for user {user_id}")
      return []
    except Exception as e:
      logger.error(f"✗ Error getting user schedules for {user_id}: {e}")
      return []

  def change_user_password(self, user_id, current_password, new_password):
    """Change user password (thread-safe)"""
    logger.info(f"=== CHANGING PASSWORD FOR USER: {user_id} ===")
    try:
      result = self._run_in_websocket_thread('user.change_password', {
        'user_id': int(user_id),
        'current_password': current_password,
        'new_password': new_password
      })

      success = result is not None
      logger.info(f"{'✓' if success else '✗'} Password change {'successful' if success else 'failed'}")
      return success, result
    except Exception as e:
      logger.error(f"✗ Error changing password for user {user_id}: {e}")
      return False, {'error': str(e)}

  def update_user_profile(self, user_id, user_data):
    """Update user profile (thread-safe)"""
    logger.info(f"=== UPDATING USER PROFILE: {user_id} ===")
    try:
      # Convert rank string to integer for server
      if 'rank' in user_data:
        user_data['rank'] = convert_rank_string_to_int(user_data['rank'])
      
      result = self._run_in_websocket_thread('user.update', {
        'user_id': int(user_id),
        'attributes': user_data
      })
      
      success = result is not None
      logger.info(f"{'✓' if success else '✗'} Profile update {'successful' if success else 'failed'}")
      return success, result
    except Exception as e:
      logger.error(f"✗ Error updating user profile {user_id}: {e}")
      return False, {'error': str(e)}

  def get_credentials(self):
    """Get all credentials (thread-safe)"""
    logger.info("=== GETTING CREDENTIALS ===")
    try:
      result = self._run_in_websocket_thread('credential.read', {'credential_id': 0})
      
      if result and 'data' in result:
        credentials = []
        for cred_data in result['data']:
          # Extract owner ID from relationship data
          owner_id = None
          owner_name = 'Unknown'
          if (cred_data.get('relationships', {}).get('owner', {}).get('data', {}).get('id')):
            owner_id = cred_data.get('relationships', {}).get('owner', {}).get('data', {}).get('id')
            # Fetch user data to get username
            try:
              user_result = self._run_in_websocket_thread('user.read', {'user_id': int(owner_id)})
              if user_result and 'data' in user_result and user_result['data']:
                user_data = user_result['data']
                if isinstance(user_data, list) and len(user_data) > 0:
                  user_data = user_data[0]
                owner_name = user_data.get('attributes', {}).get('username', 'Unknown')
            except Exception as e:
              logger.warning(f"Could not fetch user {owner_id}: {e}")
              owner_name = f"User {owner_id}"
          
          credential = {
            'id': cred_data.get('id'),
            'type': cred_data.get('type'),
            'alias': cred_data.get('attributes', {}).get('alias'),
            'description': cred_data.get('attributes', {}).get('description'),
            'owner_id': owner_id,
            'owner_name': owner_name,
            'validity_enabled': cred_data.get('attributes', {}).get('validity-enabled', False),  # Handle hyphens from server
            'validity_start': cred_data.get('attributes', {}).get('validity-start'),  # Handle hyphens from server
            'validity_end': cred_data.get('attributes', {}).get('validity-end'),  # Handle hyphens from server
            'version': cred_data.get('attributes', {}).get('version', 0)
          }
          
          # Add RFID-specific fields
          if cred_data.get('type') == 'rfid-card':
            card_id = cred_data.get('attributes', {}).get('card-id')  # Handle hyphens from server
            nb_bits = cred_data.get('attributes', {}).get('nb-bits')  # Handle hyphens from server
            logger.debug(f"RFID Card {cred_data.get('id')}: card_id='{card_id}', nb_bits={nb_bits}")
            credential.update({
              'card_id': card_id,  # Handle hyphens from server
              'nb_bits': nb_bits,  # Handle hyphens from server
              'display_identifier': card_id  # Handle hyphens from server
            })
          elif cred_data.get('type') == 'pin-code':
            credential.update({
              'code': cred_data.get('attributes', {}).get('code'),
              'display_identifier': '***' + cred_data.get('attributes', {}).get('code', '')[-4:] if cred_data.get('attributes', {}).get('code') else 'N/A'
            })
          
          credentials.append(credential)
        logger.info(f"✓ Retrieved {len(credentials)} credentials")
        return credentials
      logger.warning("✗ No credentials data in response")
      return []
    except Exception as e:
      logger.error(f"✗ Error getting credentials: {e}")
      return []

  def get_credential(self, credential_id):
    """Get a specific credential by ID (thread-safe)"""
    logger.info(f"=== GETTING CREDENTIAL: {credential_id} ===")
    try:
      result = self._run_in_websocket_thread('credential.read', {'credential_id': int(credential_id)})
      
      if result and 'data' in result:
        cred_data = result['data']
        if isinstance(cred_data, list):
          if len(cred_data) > 0:
            cred_data = cred_data[0]
          else:
            logger.warning(f"✗ Credential {credential_id} not found (empty list)")
            return None
        
        # Extract owner ID from relationship data
        owner_id = None
        owner_name = 'Unknown'
        if (cred_data.get('relationships', {}).get('owner', {}).get('data', {}).get('id')):
          owner_id = cred_data.get('relationships', {}).get('owner', {}).get('data', {}).get('id')
          # Fetch user data to get username
          try:
            user_result = self._run_in_websocket_thread('user.read', {'user_id': int(owner_id)})
            if user_result and 'data' in user_result and user_result['data']:
              user_data = user_result['data']
              if isinstance(user_data, list) and len(user_data) > 0:
                user_data = user_data[0]
              owner_name = user_data.get('attributes', {}).get('username', 'Unknown')
          except Exception as e:
            logger.warning(f"Could not fetch user {owner_id}: {e}")
            owner_name = f"User {owner_id}"
        
        credential = {
          'id': cred_data.get('id'),
          'type': cred_data.get('type'),
          'alias': cred_data.get('attributes', {}).get('alias'),
          'description': cred_data.get('attributes', {}).get('description'),
          'owner_id': owner_id,
          'owner_name': owner_name,
          'validity_enabled': cred_data.get('attributes', {}).get('validity-enabled', False),  # Handle hyphens from server
          'validity_start': cred_data.get('attributes', {}).get('validity-start'),  # Handle hyphens from server
          'validity_end': cred_data.get('attributes', {}).get('validity-end'),  # Handle hyphens from server
          'version': cred_data.get('attributes', {}).get('version', 0)
        }
        
        # Add RFID-specific fields
        if cred_data.get('type') == 'rfid-card':
          card_id = cred_data.get('attributes', {}).get('card-id')  # Handle hyphens from server
          nb_bits = cred_data.get('attributes', {}).get('nb-bits')  # Handle hyphens from server
          logger.debug(f"RFID Card {credential_id}: card_id='{card_id}', nb_bits={nb_bits}")
          credential.update({
            'card_id': card_id,  # Handle hyphens from server
            'nb_bits': nb_bits,  # Handle hyphens from server
            'display_identifier': card_id  # Handle hyphens from server
          })
        elif cred_data.get('type') == 'pin-code':
          credential.update({
            'code': cred_data.get('attributes', {}).get('code'),
            'display_identifier': '***' + cred_data.get('attributes', {}).get('code', '')[-4:] if cred_data.get('attributes', {}).get('code') else 'N/A'
          })
        
        logger.info(f"✓ Retrieved credential {credential_id}")
        return credential
      logger.warning(f"✗ Credential {credential_id} not found")
      return None
    except Exception as e:
      logger.error(f"✗ Error getting credential {credential_id}: {e}")
      return None

  def create_rfid_credential(self, credential_data):
    """Create a new RFID credential (thread-safe)"""
    logger.info(f"=== CREATING RFID CREDENTIAL: {credential_data.get('alias')} ===")
    try:
      # Prepare the credential data structure matching server expectations
      rfid_data = {
        'credential-type': 'rfid-card',  # Use the model name format
        'attributes': {
          'alias': credential_data.get('alias'),
          'description': credential_data.get('description', ''),
          'card-id': credential_data.get('card_id'),  # Use hyphens like server expects
          'nb-bits': int(credential_data.get('nb_bits', 32)),  # Use hyphens like server expects
          'validity-enabled': credential_data.get('validity_enabled', False),  # Use hyphens like server expects
          'validity-start': credential_data.get('validity_start'),  # Use hyphens like server expects
          'validity-end': credential_data.get('validity_end')  # Use hyphens like server expects
        }
      }
      
      # Add owner if specified (use owner_id format like Ember)
      if credential_data.get('owner'):
        rfid_data['attributes']['owner_id'] = int(credential_data['owner'])
      else:
        rfid_data['attributes']['owner_id'] = 0
      
      logger.debug(f"Sending RFID credential data: {rfid_data}")
      logger.debug(f"Card ID being sent: '{credential_data.get('card_id')}'")
      logger.debug(f"Number of bits being sent: {credential_data.get('nb_bits')}")
      result = self._run_in_websocket_thread('credential.create', rfid_data)
      
      logger.debug(f"Raw result from credential.create: {result}")
      
      if result is None:
        logger.error("✗ RFID credential creation failed: result is None")
        return False, {'error': 'Server returned no response'}
      
      # Check if result has status information (error response)
      if isinstance(result, dict) and 'status_code' in result:
        status_code = result.get('status_code')
        status_string = result.get('status_string', 'Unknown error')
        
        if status_code == 0:
          logger.info("✓ RFID credential creation successful")
          return True, result
        else:
          logger.error(f"✗ RFID credential creation failed: {status_string}")
          return False, {'error': status_string}
      elif isinstance(result, dict):
        # Success response (content data)
        logger.info("✓ RFID credential creation successful")
        return True, result
      else:
        logger.error(f"✗ RFID credential creation failed: unexpected result type {type(result)}")
        return False, {'error': 'Unexpected response format'}
        
    except Exception as e:
      logger.error(f"✗ Error creating RFID credential: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}

  def update_rfid_credential(self, credential_id, credential_data):
    """Update an existing RFID credential (thread-safe)"""
    logger.info(f"=== UPDATING RFID CREDENTIAL: {credential_id} ===")
    try:
      # Prepare the credential data structure
      rfid_data = {
        'credential_id': int(credential_id),
        'attributes': {
          'alias': credential_data.get('alias'),
          'description': credential_data.get('description', ''),
          'card-id': credential_data.get('card_id'),  # Use hyphens like server expects
          'nb-bits': int(credential_data.get('nb_bits', 32)),  # Use hyphens like server expects
          'validity-enabled': credential_data.get('validity_enabled', False)  # Use hyphens like server expects
        }
      }
      
      # Add validity dates only if they have values
      if credential_data.get('validity_start'):
        rfid_data['attributes']['validity-start'] = credential_data.get('validity_start')
      if credential_data.get('validity_end'):
        rfid_data['attributes']['validity-end'] = credential_data.get('validity_end')
      
      # Add owner if specified
      if credential_data.get('owner'):
        rfid_data['attributes']['owner_id'] = int(credential_data['owner'])
      else:
        rfid_data['attributes']['owner_id'] = 0
      
      logger.debug(f"Sending RFID credential update data: {rfid_data}")
      logger.debug(f"Card ID being sent: '{credential_data.get('card_id')}'")
      logger.debug(f"Number of bits being sent: {credential_data.get('nb_bits')}")
      result = self._run_in_websocket_thread('credential.update', rfid_data)
      
      logger.debug(f"Raw result from credential.update: {result}")
      logger.debug(f"Result type: {type(result)}")
      logger.debug(f"Result keys: {result.keys() if isinstance(result, dict) else 'Not a dict'}")
      
      # Check if the update was successful
      if result is not None:
        # Check if it's our success indicator (from empty content responses)
        if isinstance(result, dict) and result.get('success') and result.get('status_code') == 0:
          logger.info("✓ RFID credential update successful")
          return True, result
        # Check if it's a successful response with status_code: 0
        elif isinstance(result, dict) and result.get('status_code') == 0:
          logger.info("✓ RFID credential update successful")
          return True, result
        # Check if it's an error response
        elif isinstance(result, dict) and result.get('status_code') is not None:
          error_msg = result.get('status_string', 'Unknown error')
          logger.error(f"✗ RFID credential update failed: {error_msg}")
          return False, {'error': error_msg}
        else:
          # Assume success if we got a response but no status_code (legacy behavior)
          logger.info("✓ RFID credential update successful (no status_code)")
          return True, result
      else:
        logger.error("✗ RFID credential update failed: result is None")
        return False, {'error': 'Server returned no response'}
        
    except Exception as e:
      logger.error(f"✗ Error updating RFID credential {credential_id}: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}

  def delete_credential(self, credential_id):
    """Delete a credential (thread-safe)"""
    logger.info(f"=== DELETING CREDENTIAL: {credential_id} ===")
    try:
      result = self._run_in_websocket_thread('credential.delete', {
        'credential_id': int(credential_id)
      })

      success = result is not None
      logger.info(f"{'✓' if success else '✗'} Credential deletion {'successful' if success else 'failed'}")
      return success, result
    except Exception as e:
      logger.error(f"✗ Error deleting credential {credential_id}: {e}")
      return False, {'error': str(e)}

  def get_schedules(self):
    """Get all schedules (thread-safe)"""
    logger.info("=== GETTING SCHEDULES ===")
    try:
      result = self._run_in_websocket_thread('schedule.read', {'schedule_id': 0})
      
      if result and 'data' in result:
        schedules = []
        for schedule_data in result['data']:
          schedule = {
            'id': schedule_data.get('id'),
            'name': schedule_data.get('attributes', {}).get('name'),
            'description': schedule_data.get('attributes', {}).get('description'),
            'timeframes': schedule_data.get('attributes', {}).get('timeframes', []),
            'version': schedule_data.get('attributes', {}).get('version', 0)
          }
          schedules.append(schedule)
        logger.info(f"✓ Retrieved {len(schedules)} schedules")
        return schedules
      logger.warning("✗ No schedules data in response")
      return []
    except Exception as e:
      logger.error(f"✗ Error getting schedules: {e}")
      return []

  def get_schedule(self, schedule_id):
    """Get a specific schedule by ID (thread-safe)"""
    logger.info(f"=== GETTING SCHEDULE: {schedule_id} ===")
    try:
      result = self._run_in_websocket_thread('schedule.read', {'schedule_id': int(schedule_id)})
      
      if result and 'data' in result:
        schedule_data = result['data']
        if isinstance(schedule_data, list):
          if len(schedule_data) > 0:
            schedule_data = schedule_data[0]
          else:
            logger.warning(f"✗ Schedule {schedule_id} not found (empty list)")
            return None
        
        schedule = {
          'id': schedule_data.get('id'),
          'name': schedule_data.get('attributes', {}).get('name'),
          'description': schedule_data.get('attributes', {}).get('description'),
          'timeframes': schedule_data.get('attributes', {}).get('timeframes', []),
          'mapping': [],
          'version': schedule_data.get('attributes', {}).get('version', 0)
        }
        
        # Extract mapping data from included section
        if 'included' in result:
          for included_item in result['included']:
            if included_item.get('type') == 'schedule-mapping':
              mapping = {
                'id': included_item.get('id'),
                'alias': included_item.get('attributes', {}).get('alias'),
                'users': [],
                'groups': [],
                'credentials': [],
                'doors': [],
                'zones': []  # Add missing zones field
              }
              
              # Extract user IDs from relationships
              users_data = included_item.get('relationships', {}).get('users', {}).get('data', [])
              if isinstance(users_data, dict):
                users_data = [users_data]
              mapping['users'] = [user.get('id') for user in users_data]
              
              # Extract group IDs from relationships
              groups_data = included_item.get('relationships', {}).get('groups', {}).get('data', [])
              if isinstance(groups_data, dict):
                groups_data = [groups_data]
              mapping['groups'] = [group.get('id') for group in groups_data]
              
              # Extract credential IDs from relationships
              credentials_data = included_item.get('relationships', {}).get('credentials', {}).get('data', [])
              if isinstance(credentials_data, dict):
                credentials_data = [credentials_data]
              mapping['credentials'] = [cred.get('id') for cred in credentials_data]
              
              # Extract door IDs from relationships
              doors_data = included_item.get('relationships', {}).get('doors', {}).get('data', [])
              if isinstance(doors_data, dict):
                doors_data = [doors_data]
              mapping['doors'] = [door.get('id') for door in doors_data]
              
              # Extract zone IDs from relationships
              zones_data = included_item.get('relationships', {}).get('zones', {}).get('data', [])
              if isinstance(zones_data, dict):
                zones_data = [zones_data]
              mapping['zones'] = [zone.get('id') for zone in zones_data]
              
              schedule['mapping'].append(mapping)
        
        logger.info(f"✓ Retrieved schedule {schedule_id}")
        return schedule
      logger.warning(f"✗ Schedule {schedule_id} not found")
      return None
    except Exception as e:
      logger.error(f"✗ Error getting schedule {schedule_id}: {e}")
      return None

  def create_schedule(self, schedule_data):
    """Create a new schedule (thread-safe)"""
    logger.info(f"=== CREATING SCHEDULE ===")
    logger.info(f"Schedule data: {schedule_data}")
    try:
      result = self._run_in_websocket_thread('schedule.create', {
        'attributes': schedule_data
      })
      
      logger.debug(f"Raw result from schedule.create: {result}")
      
      if result and 'data' in result:
        schedule = {
          'id': result['data'].get('id'),
          'name': result['data'].get('attributes', {}).get('name'),
          'description': result['data'].get('attributes', {}).get('description'),
          'timeframes': result['data'].get('attributes', {}).get('timeframes', []),
          'version': result['data'].get('attributes', {}).get('version', 0)
        }
        logger.info(f"✓ Schedule created successfully with ID: {schedule['id']}")
        logger.info(f"Created schedule timeframes: {schedule['timeframes']}")
        return True, schedule
      else:
        logger.error("✗ Schedule creation failed: no data in response")
        return False, {'error': 'No data in response'}
    except Exception as e:
      logger.error(f"✗ Error creating schedule: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}

  def update_schedule(self, schedule_id, schedule_data, mapping_data=None):
    """Update a schedule (thread-safe)"""
    logger.info(f"=== UPDATING SCHEDULE: {schedule_id} ===")
    logger.info(f"Schedule data: {schedule_data}")
    logger.info(f"Mapping data: {mapping_data}")
    try:
      params = {
        'schedule_id': int(schedule_id),
        'attributes': schedule_data
      }
      
      # Add mapping data if provided
      if mapping_data:
        params['mapping'] = mapping_data
      else:
        # Always include mapping field (even if empty) like Ember does
        params['mapping'] = []
      
      logger.debug(f"Sending schedule.update with params: {params}")
      result = self._run_in_websocket_thread('schedule.update', params)
      
      logger.debug(f"Raw result from schedule.update: {result}")
      
      # For updates, the server returns the updated schedule data
      if result and 'data' in result:
        schedule = {
          'id': result['data'].get('id'),
          'name': result['data'].get('attributes', {}).get('name'),
          'description': result['data'].get('attributes', {}).get('description'),
          'timeframes': result['data'].get('attributes', {}).get('timeframes', []),
          'version': result['data'].get('attributes', {}).get('version', 0)
        }
        logger.info(f"✓ Schedule {schedule_id} updated successfully")
        logger.info(f"Updated schedule timeframes: {schedule['timeframes']}")
        return True, schedule
      else:
        logger.error(f"✗ Schedule update failed: no data in response")
        logger.error(f"Result: {result}")
        return False, {'error': 'No data in response'}
    except Exception as e:
      logger.error(f"✗ Error updating schedule {schedule_id}: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}

  def delete_schedule(self, schedule_id):
    """Delete a schedule (thread-safe)"""
    logger.info(f"=== DELETING SCHEDULE: {schedule_id} ===")
    try:
      result = self._run_in_websocket_thread('schedule.delete', {'schedule_id': int(schedule_id)})
      
      logger.debug(f"Raw result from schedule.delete: {result}")
      
      # For deletes, the server returns an empty response on success
      if result is not None:
        logger.info(f"✓ Schedule {schedule_id} deleted successfully")
        return True, result
      else:
        logger.error(f"✗ Schedule deletion failed: result is None")
        return False, {'error': 'Server returned no response'}
    except Exception as e:
      logger.error(f"✗ Error deleting schedule {schedule_id}: {e}")
      return False, {'error': str(e)}

  def get_groups(self):
    """Get all groups (thread-safe)"""
    logger.info("=== GETTING GROUPS ===")
    try:
      result = self._run_in_websocket_thread('group.read', {'group_id': 0})
      if result and 'data' in result:
        groups = []
        for group_data in result['data']:
          group = {
            'id': group_data.get('id'),
            'name': group_data.get('attributes', {}).get('name'),
            'description': group_data.get('attributes', {}).get('description'),
            'version': group_data.get('attributes', {}).get('version', 0)
          }
          groups.append(group)
        logger.info(f"✓ Retrieved {len(groups)} groups")
        return groups
      logger.warning("✗ No groups data in response")
      return []
    except Exception as e:
      logger.error(f"✗ Error getting groups: {e}")
      return []

  def get_doors(self):
    """Get all doors (thread-safe)"""
    logger.info("=== GETTING DOORS ===")
    try:
      result = self._run_in_websocket_thread('door.read', {'door_id': 0})
      if result and 'data' in result:
        doors = []
        for door_data in result['data']:
          door = {
            'id': door_data.get('id'),
            'name': door_data.get('attributes', {}).get('name'),
            'description': door_data.get('attributes', {}).get('description'),
            'zone': door_data.get('relationships', {}).get('zone', {}).get('data', {}).get('id'),
            'version': door_data.get('attributes', {}).get('version', 0)
          }
          doors.append(door)
        logger.info(f"✓ Retrieved {len(doors)} doors")
        return doors
      logger.warning("✗ No doors data in response")
      return []
    except Exception as e:
      logger.error(f"✗ Error getting doors: {e}")
      return []

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
                return render_template('users/create.html', user_data=request.form, ranks=USER_RANKS)

            # Get form data
            user_data = {
                'username': request.form.get('username'),
                'firstname': request.form.get('firstname'),
                'lastname': request.form.get('lastname'),
                'email': request.form.get('email'),
                'password': request.form.get('password'),
                'rank': request.form.get('rank', 'user'),
                'validity_enabled': request.form.get('validity_enabled') == 'on',
                'validity_start': request.form.get('validity_start'),
                'validity_end': request.form.get('validity_end')
            }

            # Validate required fields
            if not all([user_data['username'], user_data['firstname'],
                       user_data['lastname'], user_data['email'], user_data['password']]):
                flash('All fields are required', 'error')
                return render_template('users/create.html', user_data=user_data, ranks=USER_RANKS)

            # Create user via WebSocket
            success, result = leosac_client.create_user(user_data)

            if success:
                flash('User created successfully!', 'success')
                return redirect(url_for('users_list'))
            else:
                error_msg = result.get('status_string', 'Unknown error')
                flash(f'Failed to create user: {error_msg}', 'error')
                return render_template('users/create.html', user_data=user_data, ranks=USER_RANKS)

        except Exception as e:
            flash(f'Error creating user: {str(e)}', 'error')
            return render_template('users/create.html', user_data=request.form, ranks=USER_RANKS)

    # Available user ranks
    return render_template('users/create.html', ranks=USER_RANKS)

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
    """List all credentials"""
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            logger.warning('WebSocket connection not available in credentials_list route.')
            flash('WebSocket connection not available. Please try again.', 'error')
            return render_template('credentials/list.html', credentials=[])
        credentials = leosac_client.get_credentials()
        return render_template('credentials/list.html', credentials=credentials)
    except Exception as e:
        logger.error(f'Error loading credentials: {str(e)}')
        flash(f'Error loading credentials: {str(e)}', 'error')
        return render_template('credentials/list.html', credentials=[])

@app.route('/credentials/rfid/create', methods=['GET', 'POST'])
@login_required
def credentials_rfid_create():
    """Create a new RFID credential"""
    if request.method == 'POST':
        try:
            # Check if WebSocket client is connected
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return render_template('credentials/rfid_create.html', credential_data=request.form, users=[])

            # Get form data
            credential_data = {
                'alias': request.form.get('alias'),
                'card_id': request.form.get('card_id'),
                'nb_bits': request.form.get('nb_bits', 32),
                'description': request.form.get('description', ''),
                'owner': request.form.get('owner'),
                'validity_enabled': request.form.get('validity_enabled') == 'on',
                'validity_start': request.form.get('validity_start'),
                'validity_end': request.form.get('validity_end')
            }

            # Validate required fields
            if not all([credential_data['alias'], credential_data['card_id'], credential_data['nb_bits']]):
                flash('Alias, Card ID, and Number of Bits are required', 'error')
                return render_template('credentials/rfid_create.html', credential_data=credential_data, users=[])

            # Validate card ID format - use the same regex as Ember (allows variable length)
            import re
            hex_regex = re.compile(r'^[0-9A-F]{2}(?::[0-9A-F]{2})*$', re.IGNORECASE)
            if not hex_regex.match(credential_data['card_id']):
                flash('Invalid card ID format. Use hex format like 00:22:28:c8 (hex pairs separated by colons)', 'error')
                return render_template('credentials/rfid_create.html', credential_data=credential_data, users=[])

            # Validate number of bits
            try:
                nb_bits = int(credential_data['nb_bits'])
                if nb_bits <= 0 or nb_bits % 8 != 0:
                    flash('Number of bits must be positive and divisible by 8', 'error')
                    return render_template('credentials/rfid_create.html', credential_data=credential_data, users=[])
            except ValueError:
                flash('Number of bits must be a valid integer', 'error')
                return render_template('credentials/rfid_create.html', credential_data=credential_data, users=[])

            # Create credential via WebSocket
            success, result = leosac_client.create_rfid_credential(credential_data)

            if success:
                flash('RFID credential created successfully!', 'success')
                return redirect(url_for('credentials_list'))
            else:
                # Handle different error response formats
                if isinstance(result, dict):
                    error_msg = result.get('error', result.get('status_string', 'Unknown error'))
                else:
                    error_msg = str(result) if result else 'Unknown error'
                flash(f'Failed to create RFID credential: {error_msg}', 'error')
                return render_template('credentials/rfid_create.html', credential_data=credential_data, users=[])

        except Exception as e:
            flash(f'Error creating RFID credential: {str(e)}', 'error')
            return render_template('credentials/rfid_create.html', credential_data=request.form, users=[])

    # Get users for the dropdown
    try:
        users = leosac_client.get_users()
    except Exception as e:
        logger.error(f'Error loading users for RFID create: {str(e)}')
        users = []

    return render_template('credentials/rfid_create.html', users=users)

@app.route('/credentials/pin/create')
@login_required
def credentials_pin_create():
    return render_template('credentials/pin_create.html')

@app.route('/credentials/<int:credential_id>')
@login_required
def credential_view(credential_id):
    """View a specific credential"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('credentials_list'))

        # Get credential details from WebSocket
        credential = leosac_client.get_credential(credential_id)

        if credential:
            return render_template('credentials/view.html', credential=credential)
        else:
            flash('Credential not found', 'error')
            return redirect(url_for('credentials_list'))

    except Exception as e:
        flash(f'Error loading credential: {str(e)}', 'error')
        return redirect(url_for('credentials_list'))

@app.route('/credentials/<int:credential_id>/edit', methods=['GET', 'POST'])
@login_required
def credential_edit(credential_id):
    """Edit a specific credential"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('credential_view', credential_id=credential_id))

        # Get credential details
        credential = leosac_client.get_credential(credential_id)
        if not credential:
            flash('Credential not found', 'error')
            return redirect(url_for('credentials_list'))

        if request.method == 'POST':
            # Get form data
            credential_data = {
                'alias': request.form.get('alias'),
                'description': request.form.get('description', ''),
                'owner': request.form.get('owner'),
                'validity_enabled': request.form.get('validity_enabled') == 'on',
                'validity_start': request.form.get('validity_start'),
                'validity_end': request.form.get('validity_end')
            }

            # Add RFID-specific fields
            if credential['type'] == 'rfid-card':
                credential_data.update({
                    'card_id': request.form.get('card_id'),
                    'nb_bits': request.form.get('nb_bits', 32)
                })

            # Validate required fields
            if not credential_data['alias']:
                flash('Alias is required', 'error')
                return render_template('credentials/edit.html', credential=credential, users=[])

            # Validate card ID format for RFID cards - server expects flexible hex format
            if credential['type'] == 'rfid-card':
                import re
                hex_regex = re.compile(r'^[0-9A-F]{2}(?::[0-9A-F]{2})*$', re.IGNORECASE)
                if not hex_regex.match(credential_data['card_id']):
                    flash('Invalid card ID format. Use hex format like aa:bb:cc:11 (hex pairs separated by colons)', 'error')
                    return render_template('credentials/edit.html', credential=credential, users=[])

            # Update credential via WebSocket
            if credential['type'] == 'rfid-card':
                success, result = leosac_client.update_rfid_credential(credential_id, credential_data)
            else:
                # TODO: Add PIN code update method
                flash('PIN code editing not yet implemented', 'error')
                return render_template('credentials/edit.html', credential=credential, users=[])

            if success:
                flash('Credential updated successfully!', 'success')
                return redirect(url_for('credential_view', credential_id=credential_id))
            else:
                # Handle different error response formats
                if isinstance(result, dict):
                    error_msg = result.get('error', result.get('status_string', 'Unknown error'))
                else:
                    error_msg = str(result) if result else 'Unknown error'
                flash(f'Failed to update credential: {error_msg}', 'error')
                return render_template('credentials/edit.html', credential=credential, users=[])

        # Get users for the dropdown
        try:
            users = leosac_client.get_users()
        except Exception as e:
            logger.error(f'Error loading users for credential edit: {str(e)}')
            users = []

        return render_template('credentials/edit.html', credential=credential, users=users)

    except Exception as e:
        flash(f'Error editing credential: {str(e)}', 'error')
        return redirect(url_for('credential_view', credential_id=credential_id))

@app.route('/credentials/<int:credential_id>/delete', methods=['POST'])
@login_required
def credential_delete(credential_id):
    """Delete a credential"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('credentials_list'))

        # Delete credential via WebSocket
        success, result = leosac_client.delete_credential(credential_id)

        if success:
            flash('Credential deleted successfully!', 'success')
        else:
            error_msg = result.get('status_string', 'Unknown error')
            flash(f'Failed to delete credential: {error_msg}', 'error')

    except Exception as e:
        flash(f'Error deleting credential: {str(e)}', 'error')

    return redirect(url_for('credentials_list'))

@app.route('/schedules')
@login_required
def schedules_list():
    """List all schedules"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('index'))

        # Get schedules from WebSocket
        schedules = leosac_client.get_schedules()

        return render_template('schedules/list.html', schedules=schedules)
    except Exception as e:
        logger.error(f"Error in schedules_list: {e}")
        flash('Error loading schedules. Please try again.', 'error')
        return redirect(url_for('index'))

@app.route('/schedules/create', methods=['GET', 'POST'])
@login_required
def schedules_create():
    """Create a new schedule"""
    if request.method == 'POST':
        try:
            # Check if WebSocket client is connected
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return redirect(url_for('schedules_list'))

            # Get form data
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            
            # Validate required fields
            if not name:
                flash('Schedule name is required.', 'error')
                return render_template('schedules/create.html')
            
            if len(name) < 3:
                flash('Schedule name must be at least 3 characters long.', 'error')
                return render_template('schedules/create.html')
            
            if len(name) > 50:
                flash('Schedule name must be no more than 50 characters long.', 'error')
                return render_template('schedules/create.html')

            # Validate character restrictions (matching server validation)
            if not re.match(r'^[a-zA-Z0-9_.-]+$', name):
                flash('Schedule name can only contain letters, numbers, underscores (_), hyphens (-), and periods (.). No spaces or other characters are allowed.', 'error')
                return render_template('schedules/create.html')

            # Process timeframes from form data
            timeframes = []
            timeframe_counter = 0
            
            logger.info("=== PROCESSING TIMEFRAMES FROM FORM (CREATE) ===")
            logger.info(f"Form data keys: {list(request.form.keys())}")
            
            # Get all timeframe data from the form
            while f'timeframes[{timeframe_counter}][start_time]' in request.form:
                start_time = request.form.get(f'timeframes[{timeframe_counter}][start_time]')
                end_time = request.form.get(f'timeframes[{timeframe_counter}][end_time]')
                
                logger.info(f"Processing timeframe {timeframe_counter}: start_time={start_time}, end_time={end_time}")
                
                if start_time and end_time:
                    # Get selected days for this timeframe
                    selected_days = []
                    for day_name, day_value in [
                        ('monday', 0), ('tuesday', 1), ('wednesday', 2), 
                        ('thursday', 3), ('friday', 4), ('saturday', 5), ('sunday', 6)
                    ]:
                        # Check if checkbox is checked (checkbox value is present in form data)
                        if f'timeframes[{timeframe_counter}][days][{day_name}]' in request.form:
                            selected_days.append(day_value)
                            logger.info(f"  Day {day_name} (value {day_value}) selected")
                    
                    # Create a separate timeframe for each selected day (like Ember does)
                    for day in selected_days:
                        timeframe = {
                            'id': len(timeframes),
                            'start-time': start_time,  # Use hyphenated field name
                            'end-time': end_time,      # Use hyphenated field name
                            'day': day
                        }
                        timeframes.append(timeframe)
                        logger.info(f"  Created timeframe: {timeframe}")
                
                timeframe_counter += 1

            logger.info(f"Final timeframes array: {timeframes}")

            # Create schedule data
            schedule_data = {
                'name': name,
                'description': description,
                'timeframes': timeframes
            }

            # Create schedule via WebSocket
            success, result = leosac_client.create_schedule(schedule_data)

            if success:
                flash('Schedule created successfully!', 'success')
                return redirect(url_for('schedule_view', schedule_id=result['id']))
            else:
                error_msg = result.get('error', 'Unknown error occurred')
                flash(f'Failed to create schedule: {error_msg}', 'error')
                return render_template('schedules/create.html')

        except Exception as e:
            logger.error(f"Error creating schedule: {e}")
            flash('Error creating schedule. Please try again.', 'error')
            return render_template('schedules/create.html')

    return render_template('schedules/create.html')

# Hardware management routes
@app.route('/schedules/<int:schedule_id>')
@login_required
def schedule_view(schedule_id):
    """View a specific schedule"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('schedules_list'))

        # Get schedule from WebSocket
        schedule = leosac_client.get_schedule(schedule_id)

        if schedule:
            # Group timeframes for display
            if schedule.get('timeframes'):
                schedule['timeframes'] = group_timeframes_for_display(schedule['timeframes'])
                logger.info(f"Grouped timeframes for display: {schedule['timeframes']}")
            
            return render_template('schedules/view.html', schedule=schedule)
        else:
            flash('Schedule not found.', 'error')
            return redirect(url_for('schedules_list'))

    except Exception as e:
        logger.error(f"Error in schedule_view: {e}")
        flash('Error loading schedule. Please try again.', 'error')
        return redirect(url_for('schedules_list'))

# Helper function to group timeframes by time for display
def group_timeframes_for_display(timeframes):
    """Group timeframes by start/end time for display in the UI"""
    if not timeframes:
        return []
    
    # Group timeframes by start and end time
    grouped = {}
    for tf in timeframes:
        start_time = tf.get('start-time') or tf.get('start_time')
        end_time = tf.get('end-time') or tf.get('end_time')
        day = tf.get('day')
        
        if start_time and end_time:
            key = f"{start_time}-{end_time}"
            if key not in grouped:
                grouped[key] = {
                    'start_time': start_time,
                    'end_time': end_time,
                    'days': set()
                }
            grouped[key]['days'].add(day)
    
    # Convert to list format for template
    result = []
    for i, (key, data) in enumerate(grouped.items()):
        timeframe = {
            'id': i,
            'start_time': data['start_time'],
            'end_time': data['end_time'],
            'days': data['days']
        }
        result.append(timeframe)
    
    return result

@app.route('/schedules/<int:schedule_id>/edit', methods=['GET', 'POST'])
@login_required
def schedule_edit(schedule_id):
    """Edit a schedule"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('schedules_list'))

        # Get current schedule data
        schedule = leosac_client.get_schedule(schedule_id)
        if not schedule:
            flash('Schedule not found.', 'error')
            return redirect(url_for('schedules_list'))

        # Fetch all users, groups, credentials, and doors for mapping UI
        users = leosac_client.get_users()
        groups = leosac_client.get_groups()
        credentials = leosac_client.get_credentials()
        doors = leosac_client.get_doors()

        # Group timeframes for display
        if schedule.get('timeframes'):
            schedule['timeframes'] = group_timeframes_for_display(schedule['timeframes'])
            logger.info(f"Grouped timeframes for display: {schedule['timeframes']}")

        if request.method == 'POST':
            # Get form data
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()

            # Validate required fields
            if not name:
                flash('Schedule name is required.', 'error')
                return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)
            if len(name) < 3:
                flash('Schedule name must be at least 3 characters long.', 'error')
                return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)
            if len(name) > 50:
                flash('Schedule name must be no more than 50 characters long.', 'error')
                return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)
            if not re.match(r'^[a-zA-Z0-9_.-]+$', name):
                flash('Schedule name can only contain letters, numbers, underscores (_), hyphens (-), and periods (.). No spaces or other characters are allowed.', 'error')
                return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)

            # Process timeframes from form data
            timeframes = []
            timeframe_counter = 0
            logger.info("=== PROCESSING TIMEFRAMES FROM FORM ===")
            logger.info(f"Form data keys: {list(request.form.keys())}")
            while f'timeframes[{timeframe_counter}][start_time]' in request.form:
                start_time = request.form.get(f'timeframes[{timeframe_counter}][start_time]')
                end_time = request.form.get(f'timeframes[{timeframe_counter}][end_time]')
                logger.info(f"Processing timeframe {timeframe_counter}: start_time={start_time}, end_time={end_time}")
                if start_time and end_time:
                    selected_days = []
                    for day_name, day_value in [
                        ('monday', 0), ('tuesday', 1), ('wednesday', 2), 
                        ('thursday', 3), ('friday', 4), ('saturday', 5), ('sunday', 6)
                    ]:
                        if f'timeframes[{timeframe_counter}][days][{day_name}]' in request.form:
                            selected_days.append(day_value)
                            logger.info(f"  Day {day_name} (value {day_value}) selected")
                    for day in selected_days:
                        timeframe = {
                            'id': len(timeframes),
                            'start-time': start_time,
                            'end-time': end_time,
                            'day': day
                        }
                        timeframes.append(timeframe)
                        logger.info(f"  Created timeframe: {timeframe}")
                timeframe_counter += 1
            logger.info(f"Final timeframes array: {timeframes}")

            # Process mappings from form data
            mapping_data = []

            # Find all mapping indices by looking for any mapping fields
            mapping_indices = set()
            import re as _re
            for key in request.form.keys():
              if key.startswith('mappings['):
                m = _re.match(r'mappings\[(\d+)\]', key)
                if m:
                  mapping_indices.add(int(m.group(1)))

            # DEBUG: Log all mapping-related form data
            logger.info(f"Found mapping indices: {sorted(mapping_indices)}")
            logger.info("==== DETAILED MAPPING FORM DATA ====")
            for key in sorted(request.form.keys()):
              if key.startswith('mappings['):
                values = request.form.getlist(key)
                logger.info(f"MAPPING FORM: {key} => {values}")
            logger.info("==== END MAPPING FORM DATA ====")

            # Aggregate all users, groups, credentials, doors into a single mapping
            all_users = []
            all_groups = []
            all_credentials = []
            all_doors = []
            alias = None

            for idx in sorted(mapping_indices):
              this_alias = request.form.get(f'mappings[{idx}][alias]', '').strip()
              if this_alias and not alias:
                alias = this_alias  # Use the first alias found
              users_selected = request.form.getlist(f'mappings[{idx}][users][]')
              groups_selected = request.form.getlist(f'mappings[{idx}][groups][]')
              credentials_selected = request.form.getlist(f'mappings[{idx}][credentials][]')
              doors_selected = request.form.getlist(f'mappings[{idx}][doors][]')
              all_users.extend([int(uid) for uid in users_selected if uid and uid.strip()])
              all_groups.extend([int(gid) for gid in groups_selected if gid and gid.strip()])
              all_credentials.extend([int(cid) for cid in credentials_selected if cid and cid.strip()])
              all_doors.extend([int(did) for did in doors_selected if did and did.strip()])

            # Remove duplicates
            all_users = list(set(all_users))
            all_groups = list(set(all_groups))
            all_credentials = list(set(all_credentials))
            all_doors = list(set(all_doors))

            mapping_data = []
            if alias and (all_users or all_groups or all_credentials or all_doors):
              mapping = {
                'alias': alias,
                'users': all_users,
                'groups': all_groups,
                'credentials': all_credentials,
                'doors': all_doors,
                'zones': []  # Not handled in UI yet
              }
              mapping_data.append(mapping)
              logger.info(f"Aggregated mapping: {mapping}")
            else:
              logger.info(f"No valid mapping to add. Alias: {alias}, users: {all_users}, groups: {all_groups}, credentials: {all_credentials}, doors: {all_doors}")

            # Update schedule data
            schedule_data = {
                'name': name,
                'description': description,
                'timeframes': timeframes
            }
            logger.debug(f"Updating schedule {schedule_id} with data: {schedule_data}")
            logger.debug(f"Mappings: {mapping_data}")
            success, result = leosac_client.update_schedule(schedule_id, schedule_data, mapping_data)
            if success:
                flash('Schedule updated successfully!', 'success')
                return redirect(url_for('schedule_view', schedule_id=schedule_id))
            else:
                error_msg = result.get('error', 'Unknown error occurred')
                flash(f'Failed to update schedule: {error_msg}', 'error')
                return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)

        return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)

    except Exception as e:
        logger.error(f"Error in schedule_edit: {e}")
        flash('Error editing schedule. Please try again.', 'error')
        return redirect(url_for('schedules_list'))

@app.route('/schedules/<int:schedule_id>/delete', methods=['POST'])
@login_required
def schedule_delete(schedule_id):
    """Delete a schedule"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('schedules_list'))

        # Delete schedule via WebSocket
        success, result = leosac_client.delete_schedule(schedule_id)

        if success:
            flash('Schedule deleted successfully!', 'success')
        else:
            error_msg = result.get('error', 'Unknown error occurred')
            flash(f'Failed to delete schedule: {error_msg}', 'error')

        return redirect(url_for('schedules_list'))

    except Exception as e:
        logger.error(f"Error deleting schedule: {e}")
        flash('Error deleting schedule. Please try again.', 'error')
        return redirect(url_for('schedules_list'))

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

        # Get user details from WebSocket (includes relationships)
        user = leosac_client.get_user(user_id)
        
        # Debug: Log the full user response to see what relationships are included
        logger.debug(f"Full user response for user {user_id}: {user}")

        if user:
            # Always fetch detailed relationship data for the user profile
            # This ensures we get all the data regardless of relationship structure
            user_groups = []
            user_credentials = []
            user_schedules = []
            
            try:
                user_groups = leosac_client.get_user_groups(user_id)
                logger.debug(f"Fetched {len(user_groups)} user groups")
            except Exception as e:
                logger.warning(f"Could not fetch user groups: {e}")
            
            try:
                user_credentials = leosac_client.get_user_credentials(user_id)
                logger.debug(f"Fetched {len(user_credentials)} user credentials")
            except Exception as e:
                logger.warning(f"Could not fetch user credentials: {e}")
            
            try:
                user_schedules = leosac_client.get_user_schedules(user_id)
                logger.debug(f"Fetched {len(user_schedules)} user schedules")
            except Exception as e:
                logger.warning(f"Could not fetch user schedules: {e}")

            return render_template('profile.html',
                                 user=user,
                                 user_groups=user_groups,
                                 user_credentials=user_credentials,
                                 user_schedules=user_schedules,
                                 ranks=USER_RANKS)
        else:
            flash('User not found', 'error')
            return redirect(url_for('users_list'))

    except Exception as e:
        flash(f'Error loading user profile: {str(e)}', 'error')
        return redirect(url_for('users_list'))

@app.route('/profile/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def profile_edit(user_id):
    """Edit user profile"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('profile', user_id=user_id))

        # Get user details
        user = leosac_client.get_user(user_id)
        if not user:
            flash('User not found', 'error')
            return redirect(url_for('users_list'))

        if request.method == 'POST':
            # Get form data
            user_data = {
                'firstname': request.form.get('firstname'),
                'lastname': request.form.get('lastname'),
                'email': request.form.get('email'),
                'rank': request.form.get('rank', 'user'),
                'validity_enabled': request.form.get('validity_enabled') == 'on',
                'validity_start': request.form.get('validity_start'),
                'validity_end': request.form.get('validity_end')
            }

            # Validate required fields
            if not all([user_data['firstname'], user_data['lastname'], user_data['email']]):
                flash('First name, last name, and email are required', 'error')
                return render_template('profile_edit.html', user=user, ranks=USER_RANKS)

            # Update user via WebSocket
            success, result = leosac_client.update_user_profile(user_id, user_data)

            if success:
                flash('Profile updated successfully!', 'success')
                return redirect(url_for('profile', user_id=user_id))
            else:
                error_msg = result.get('status_string', 'Unknown error')
                flash(f'Failed to update profile: {error_msg}', 'error')
                return render_template('profile_edit.html', user=user, ranks=USER_RANKS)

        return render_template('profile_edit.html', user=user, ranks=USER_RANKS)

    except Exception as e:
        flash(f'Error editing profile: {str(e)}', 'error')
        return redirect(url_for('profile', user_id=user_id))

@app.route('/profile/<int:user_id>/change-password', methods=['POST'])
@login_required
def profile_change_password(user_id):
    """Change user password"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('profile', user_id=user_id))

        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        new_password2 = request.form.get('new_password2')

        # Validate passwords
        if not new_password:
            flash('New password is required', 'error')
            return redirect(url_for('profile', user_id=user_id))

        if new_password != new_password2:
            flash('New passwords do not match', 'error')
            return redirect(url_for('profile', user_id=user_id))

        # Change password via WebSocket
        success, result = leosac_client.change_user_password(user_id, current_password, new_password)

        if success:
            flash('Password changed successfully!', 'success')
        else:
            error_msg = result.get('status_string', 'Unknown error')
            flash(f'Failed to change password: {error_msg}', 'error')

        return redirect(url_for('profile', user_id=user_id))

    except Exception as e:
        flash(f'Error changing password: {str(e)}', 'error')
        return redirect(url_for('profile', user_id=user_id))

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