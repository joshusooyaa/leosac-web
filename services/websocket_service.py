"""
WebSocket service for communicating with Leosac server.
"""
import os
import json
import uuid
import asyncio
import websockets
import threading
import time
import logging
import queue
import traceback
from datetime import datetime
from config.settings import WEBSOCKET_URL
from utils.rank_converter import convert_rank_int_to_string, convert_rank_string_to_int

logger = logging.getLogger(__name__)

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
        'authenticated': bool(self.auth_token and self.user_info),
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
      # Get user data to find membership IDs
      user_result = self._run_in_websocket_thread('user.read', {'user_id': int(user_id)})
      
      if not user_result or 'data' not in user_result:
        logger.warning(f"✗ User {user_id} not found")
        return []
      
      user_data = user_result['data']
      if isinstance(user_data, list) and len(user_data) > 0:
        user_data = user_data[0]
      
      # Extract membership IDs from user relationships
      memberships_data = user_data.get('relationships', {}).get('memberships', {}).get('data', [])
      if isinstance(memberships_data, dict):
        memberships_data = [memberships_data]
      
      logger.debug(f"Found {len(memberships_data)} membership references for user {user_id}")
      
      memberships = []
      for membership_ref in memberships_data:
        membership_id = membership_ref.get('id')
        if not membership_id:
          continue
          
        logger.debug(f"Fetching membership {membership_id} for user {user_id}")
        
        try:
          # Fetch individual membership
          membership_result = self._run_in_websocket_thread('user-group-membership.read', {'membership_id': int(membership_id)})
          
          if membership_result and 'data' in membership_result:
            membership_data = membership_result['data']
            
            # Convert group rank integer to string
            group_rank_int = membership_data.get('attributes', {}).get('rank', 0)
            group_rank_string = 'administrator' if group_rank_int == 2 else 'operator' if group_rank_int == 1 else 'member'
            
            # Get group ID from relationships
            group_id = membership_data.get('relationships', {}).get('group', {}).get('data', {}).get('id')
            
            # Fetch complete group details
            group_details = None
            if group_id:
              try:
                group_result = self._run_in_websocket_thread('group.read', {'group_id': int(group_id)})
                if group_result and 'data' in group_result:
                  group_data = group_result['data']
                  if isinstance(group_data, list) and len(group_data) > 0:
                    group_data = group_data[0]
                  group_details = {
                    'id': group_data.get('id'),
                    'name': group_data.get('attributes', {}).get('name'),
                    'description': group_data.get('attributes', {}).get('description'),
                    'version': group_data.get('attributes', {}).get('version', 0)
                  }
              except Exception as e:
                logger.warning(f"Could not fetch group {group_id} details: {e}")
                group_details = {'id': group_id, 'name': f'Group {group_id}', 'description': 'Unknown', 'version': 0}
            
            membership = {
              'id': membership_data.get('id'),
              'user_id': membership_data.get('attributes', {}).get('user_id'),
              'group_id': group_id,
              'rank': group_rank_string,
              'timestamp': membership_data.get('attributes', {}).get('timestamp'),
              'group': group_details or {'id': group_id, 'name': 'Unknown', 'description': 'Unknown', 'version': 0}
            }
            memberships.append(membership)
            logger.debug(f"Added membership for user {user_id}: {membership}")
          else:
            logger.warning(f"✗ Could not fetch membership {membership_id}")
            
        except Exception as e:
          logger.warning(f"✗ Error fetching membership {membership_id}: {e}")
      
      logger.info(f"✓ Retrieved {len(memberships)} group memberships for user {user_id}")
      return memberships
    except Exception as e:
      logger.error(f"✗ Error getting user groups for {user_id}: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
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

  def get_group(self, group_id):
    """Get a specific group by ID (thread-safe)"""
    logger.info(f"=== GETTING GROUP: {group_id} ===")
    try:
      result = self._run_in_websocket_thread('group.read', {'group_id': int(group_id)})
      if result and 'data' in result:
        group_data = result['data']
        if isinstance(group_data, list):
          if len(group_data) > 0:
            group_data = group_data[0]
          else:
            logger.warning(f"✗ Group {group_id} not found (empty list)")
            return None
        group = {
          'id': group_data.get('id'),
          'name': group_data.get('attributes', {}).get('name'),
          'description': group_data.get('attributes', {}).get('description'),
          'version': group_data.get('attributes', {}).get('version', 0),
          'relationships': group_data.get('relationships', {})
        }
        logger.info(f"✓ Retrieved group {group_id}")
        return group
      logger.warning(f"✗ Group {group_id} not found")
      return None
    except Exception as e:
      logger.error(f"✗ Error getting group {group_id}: {e}")
      return None

  def create_group(self, group_data):
    """Create a new group (thread-safe)"""
    logger.info(f"=== CREATING GROUP: {group_data.get('name')} ===")
    try:
      result = self._run_in_websocket_thread('group.create', {
        'attributes': group_data
      })
      if result and 'data' in result:
        group = {
          'id': result['data'].get('id'),
          'name': result['data'].get('attributes', {}).get('name'),
          'description': result['data'].get('attributes', {}).get('description'),
          'version': result['data'].get('attributes', {}).get('version', 0)
        }
        logger.info(f"✓ Group created successfully with ID: {group['id']}")
        return True, group
      else:
        logger.error("✗ Group creation failed: no data in response")
        return False, {'error': 'No data in response'}
    except Exception as e:
      logger.error(f"✗ Error creating group: {e}")
      return False, {'error': str(e)}

  def update_group(self, group_id, group_data):
    """Update an existing group (thread-safe)"""
    logger.info(f"=== UPDATING GROUP: {group_id} ===")
    try:
      result = self._run_in_websocket_thread('group.update', {
        'group_id': int(group_id),
        'attributes': group_data
      })
      if result and 'data' in result:
        group = {
          'id': result['data'].get('id'),
          'name': result['data'].get('attributes', {}).get('name'),
          'description': result['data'].get('attributes', {}).get('description'),
          'version': result['data'].get('attributes', {}).get('version', 0)
        }
        logger.info(f"✓ Group {group_id} updated successfully")
        return True, group
      else:
        logger.error(f"✗ Group update failed: no data in response")
        return False, {'error': 'No data in response'}
    except Exception as e:
      logger.error(f"✗ Error updating group {group_id}: {e}")
      return False, {'error': str(e)}

  def delete_group(self, group_id):
    """Delete a group (thread-safe)"""
    logger.info(f"=== DELETING GROUP: {group_id} ===")
    try:
      result = self._run_in_websocket_thread('group.delete', {'group_id': int(group_id)})
      if result is not None:
        logger.info(f"✓ Group {group_id} deleted successfully")
        return True, result
      else:
        logger.error(f"✗ Group deletion failed: result is None")
        return False, {'error': 'Server returned no response'}
    except Exception as e:
      logger.error(f"✗ Error deleting group {group_id}: {e}")
      return False, {'error': str(e)}

  def get_group_memberships(self, group_id):
    """Get all user-group memberships for a group (thread-safe)"""
    logger.info(f"=== GETTING MEMBERSHIPS FOR GROUP: {group_id} ===")
    try:
      # The server doesn't support filtering by group_id in membership.read, so fetch all and filter
      result = self._run_in_websocket_thread('user-group-membership.read', {'membership_id': 0})
      if result and 'data' in result:
        memberships = []
        for m in result['data']:
          if m.get('attributes', {}).get('group_id') == group_id:
            membership = {
              'id': m.get('id'),
              'user_id': m.get('attributes', {}).get('user_id'),
              'group_id': m.get('attributes', {}).get('group_id'),
              'rank': m.get('attributes', {}).get('rank'),
              'timestamp': m.get('attributes', {}).get('timestamp')
            }
            memberships.append(membership)
        logger.info(f"✓ Retrieved {len(memberships)} memberships for group {group_id}")
        return memberships
      logger.warning(f"✗ No memberships found for group {group_id}")
      return []
    except Exception as e:
      logger.error(f"✗ Error getting memberships for group {group_id}: {e}")
      return []

  def get_group_schedules(self, group_id):
    """Get all schedules mapped to a group (thread-safe)"""
    logger.info(f"=== GETTING SCHEDULES FOR GROUP: {group_id} ===")
    try:
      # Fetch all schedules and filter those mapped to this group
      schedules = self.get_schedules()
      group_schedules = []
      for schedule in schedules:
        # For each schedule, check if any mapping includes this group
        schedule_detail = self.get_schedule(schedule['id'])
        for mapping in schedule_detail.get('mapping', []):
          if group_id in mapping.get('groups', []):
            group_schedules.append(schedule)
            break
      logger.info(f"✓ Retrieved {len(group_schedules)} schedules for group {group_id}")
      return group_schedules
    except Exception as e:
      logger.error(f"✗ Error getting schedules for group {group_id}: {e}")
      return []

  def get_membership(self, membership_id):
    """Get a specific user-group membership by ID (thread-safe)"""
    logger.info(f"=== GETTING MEMBERSHIP: {membership_id} ===")
    try:
      result = self._run_in_websocket_thread('user-group-membership.read', {'membership_id': int(membership_id)})
      if result and 'data' in result:
        m = result['data']
        membership = {
          'id': m.get('id'),
          'rank': m.get('attributes', {}).get('rank'),
          'timestamp': m.get('attributes', {}).get('timestamp'),
          'group_id': None,
          'user_id': None
        }
        # Parse relationships for group_id and user_id
        group_rel = m.get('relationships', {}).get('group', {}).get('data', {})
        user_rel = m.get('relationships', {}).get('user', {}).get('data', {})
        if group_rel:
          membership['group_id'] = group_rel.get('id')
        if user_rel:
          membership['user_id'] = user_rel.get('id')
        logger.info(f"✓ Retrieved membership {membership_id}: {membership}")
        return membership
      logger.warning(f"✗ Membership {membership_id} not found")
      return None
    except Exception as e:
      logger.error(f"✗ Error getting membership {membership_id}: {e}")
      return None

  def create_membership(self, user_id, group_id, rank):
    """Create a new user-group membership (thread-safe)"""
    logger.info(f"=== CREATING MEMBERSHIP: user {user_id}, group {group_id}, rank {rank} ===")
    try:
      result = self._run_in_websocket_thread('user-group-membership.create', {
        'attributes': {
          'user_id': int(user_id),
          'group_id': int(group_id),
          'rank': int(rank)
        }
      })
      if result and 'data' in result:
        logger.info(f"✓ Membership created: {result['data']}")
        return True, result['data']
      else:
        logger.error("✗ Membership creation failed: no data in response")
        return False, {'error': 'No data in response'}
    except Exception as e:
      logger.error(f"✗ Error creating membership: {e}")
      return False, {'error': str(e)}

  def delete_membership(self, membership_id):
    """Delete a user-group membership (thread-safe)"""
    logger.info(f"=== DELETING MEMBERSHIP: {membership_id} ===")
    try:
      result = self._run_in_websocket_thread('user-group-membership.delete', {'membership_id': int(membership_id)})
      if result is not None:
        logger.info(f"✓ Membership {membership_id} deleted successfully")
        return True, result
      else:
        logger.error(f"✗ Membership deletion failed: result is None")
        return False, {'error': 'Server returned no response'}
    except Exception as e:
      logger.error(f"✗ Error deleting membership {membership_id}: {e}")
      return False, {'error': str(e)}

  def map_schedule_to_group(self, schedule_id, group_id):
    """Map a schedule to a group by updating the schedule's mapping (thread-safe)"""
    logger.info(f"=== MAPPING SCHEDULE {schedule_id} TO GROUP {group_id} ===")
    try:
      # Get the current schedule with its mappings
      schedule = self.get_schedule(schedule_id)
      if not schedule:
        logger.error(f"✗ Schedule {schedule_id} not found")
        return False, {'error': 'Schedule not found'}
      
      # Find or create a mapping that includes this group
      mapping_updated = False
      for mapping in schedule.get('mapping', []):
        if group_id in mapping.get('groups', []):
          logger.info(f"✓ Group {group_id} already mapped to schedule {schedule_id}")
          return True, {'message': 'Group already mapped'}
        
        # If this mapping has no groups, add the group to it
        if not mapping.get('groups'):
          mapping['groups'].append(group_id)
          mapping_updated = True
          break
      
      # If no suitable mapping found, create a new one
      if not mapping_updated:
        new_mapping = {
          'alias': f'Group {group_id} mapping',
          'users': [],
          'groups': [group_id],
          'credentials': [],
          'doors': [],
          'zones': []
        }
        schedule['mapping'].append(new_mapping)
        mapping_updated = True
      
      if mapping_updated:
        # Update the schedule with the new mapping
        schedule_data = {
          'name': schedule['name'],
          'description': schedule['description'],
          'timeframes': schedule['timeframes']
        }
        
        success, result = self.update_schedule(schedule_id, schedule_data, schedule['mapping'])
        if success:
          logger.info(f"✓ Successfully mapped schedule {schedule_id} to group {group_id}")
          return True, result
        else:
          logger.error(f"✗ Failed to update schedule mapping: {result}")
          return False, result
      else:
        logger.error(f"✗ Could not create or update mapping for group {group_id}")
        return False, {'error': 'Could not create mapping'}
        
    except Exception as e:
      logger.error(f"✗ Error mapping schedule {schedule_id} to group {group_id}: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}

  def unmap_schedule_from_group(self, schedule_id, group_id):
    """Unmap a schedule from a group by updating the schedule's mapping (thread-safe)"""
    logger.info(f"=== UNMAPPING SCHEDULE {schedule_id} FROM GROUP {group_id} ===")
    try:
      # Get the current schedule with its mappings
      schedule = self.get_schedule(schedule_id)
      if not schedule:
        logger.error(f"✗ Schedule {schedule_id} not found")
        return False, {'error': 'Schedule not found'}
      
      # Find mappings that include this group and remove the group
      mapping_updated = False
      for mapping in schedule.get('mapping', []):
        if group_id in mapping.get('groups', []):
          mapping['groups'].remove(group_id)
          mapping_updated = True
          logger.info(f"✓ Removed group {group_id} from mapping")
      
      if mapping_updated:
        # Update the schedule with the modified mapping
        schedule_data = {
          'name': schedule['name'],
          'description': schedule['description'],
          'timeframes': schedule['timeframes']
        }
        
        success, result = self.update_schedule(schedule_id, schedule_data, schedule['mapping'])
        if success:
          logger.info(f"✓ Successfully unmapped schedule {schedule_id} from group {group_id}")
          return True, result
        else:
          logger.error(f"✗ Failed to update schedule mapping: {result}")
          return False, result
      else:
        logger.warning(f"✗ Group {group_id} not found in any mapping for schedule {schedule_id}")
        return False, {'error': 'Group not mapped to this schedule'}
        
    except Exception as e:
      logger.error(f"✗ Error unmapping schedule {schedule_id} from group {group_id}: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}

  # Door-related methods
  def get_doors(self):
    """Get all doors (thread-safe)"""
    logger.info("=== GETTING DOORS ===")
    try:
      auth_state = self.get_auth_state()
      logger.debug(f"Auth state for doors: {auth_state}")
      
      if not auth_state['connected']:
        logger.error("✗ WebSocket not connected")
        return []
      
      if not auth_state['authenticated']:
        logger.error("✗ Not authenticated")
        return []
      
      # Send door list request
      logger.debug("Sending door.read request with door_id=0")
      result = self._run_in_websocket_thread('door.read', {'door_id': 0})
      
      logger.debug(f"Door read result: {result}")
      
      if result and 'data' in result:
        doors_data = result.get('data', [])
        logger.info(f"✓ Retrieved {len(doors_data)} doors")
        logger.debug(f"Raw doors data: {doors_data}")
        return doors_data
      else:
        error_msg = result.get('status_string', 'Unknown error') if result else 'No response'
        logger.error(f"✗ Failed to get doors: {error_msg}")
        logger.error(f"Full error result: {result}")
        return []
        
    except Exception as e:
      logger.error(f"✗ Error getting doors: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return []

  def get_door(self, door_id):
    """Get a specific door by ID (thread-safe)"""
    logger.info(f"=== GETTING DOOR {door_id} ===")
    try:
      auth_state = self.get_auth_state()
      logger.debug(f"Auth state for door {door_id}: {auth_state}")
      
      if not auth_state['connected']:
        logger.error("✗ WebSocket not connected")
        return None
      
      if not auth_state['authenticated']:
        logger.error("✗ Not authenticated")
        return None
      
      # Send door read request
      logger.debug(f"Sending door.read request with door_id={door_id}")
      result = self._run_in_websocket_thread('door.read', {'door_id': door_id})
      
      logger.debug(f"Door {door_id} read result: {result}")
      
      if result and 'data' in result:
        door_data = result.get('data')
        if isinstance(door_data, list) and len(door_data) > 0:
          door_data = door_data[0]
        elif not door_data:
          logger.warning(f"✗ Door {door_id} not found (empty data)")
          return None
        
        logger.info(f"✓ Retrieved door {door_id}")
        logger.debug(f"Raw door data: {door_data}")
        return door_data
      else:
        error_msg = result.get('status_string', 'Unknown error') if result else 'No response'
        logger.error(f"✗ Failed to get door {door_id}: {error_msg}")
        logger.error(f"Full error result: {result}")
        return None
        
    except Exception as e:
      logger.error(f"✗ Error getting door {door_id}: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return None

  def create_door(self, door_data):
    """Create a new door (thread-safe)"""
    logger.info("=== CREATING DOOR ===")
    try:
      auth_state = self.get_auth_state()
      if not auth_state['connected']:
        logger.error("✗ WebSocket not connected")
        return False, {'error': 'WebSocket not connected'}
      
      if not auth_state['authenticated']:
        logger.error("✗ Not authenticated")
        return False, {'error': 'Not authenticated'}
      
      # Prepare door attributes
      attributes = {
        'alias': door_data.get('alias', ''),
        'description': door_data.get('description', '')
      }
      
      # Add access point if specified
      if door_data.get('access_point_id'):
        attributes['access_point_id'] = door_data['access_point_id']
      
      # Send door create request
      result = self._run_in_websocket_thread('door.create', {'attributes': attributes})
      
      if result and 'data' in result:
        logger.info("✓ Door created successfully")
        return True, result.get('data', {})
      else:
        error_msg = result.get('status_string', 'Unknown error') if result else 'No response'
        logger.error(f"✗ Failed to create door: {error_msg}")
        return False, {'error': error_msg}
        
    except Exception as e:
      logger.error(f"✗ Error creating door: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}

  def update_door(self, door_id, door_data):
    """Update an existing door (thread-safe)"""
    logger.info(f"=== UPDATING DOOR {door_id} ===")
    try:
      auth_state = self.get_auth_state()
      if not auth_state['connected']:
        logger.error("✗ WebSocket not connected")
        return False, {'error': 'WebSocket not connected'}
      
      if not auth_state['authenticated']:
        logger.error("✗ Not authenticated")
        return False, {'error': 'Not authenticated'}
      
      # Prepare door attributes
      attributes = {}
      if 'alias' in door_data:
        attributes['alias'] = door_data['alias']
      if 'description' in door_data:
        attributes['description'] = door_data['description']
      if 'access_point_id' in door_data:
        attributes['access_point_id'] = door_data['access_point_id']
      
      # Send door update request
      result = self._run_in_websocket_thread('door.update', {
        'door_id': door_id,
        'attributes': attributes
      })
      
      if result and 'data' in result:
        logger.info(f"✓ Door {door_id} updated successfully")
        return True, result.get('data', {})
      else:
        error_msg = result.get('status_string', 'Unknown error') if result else 'No response'
        logger.error(f"✗ Failed to update door {door_id}: {error_msg}")
        return False, {'error': error_msg}
        
    except Exception as e:
      logger.error(f"✗ Error updating door {door_id}: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}

  def delete_door(self, door_id):
    """Delete a door (thread-safe)"""
    logger.info(f"=== DELETING DOOR {door_id} ===")
    try:
      auth_state = self.get_auth_state()
      if not auth_state['connected']:
        logger.error("✗ WebSocket not connected")
        return False, {'error': 'WebSocket not connected'}
      
      if not auth_state['authenticated']:
        logger.error("✗ Not authenticated")
        return False, {'error': 'Not authenticated'}
      
      # Send door delete request
      result = self._run_in_websocket_thread('door.delete', {'door_id': door_id})
      
      if result is not None:  # Delete operations typically return None on success
        logger.info(f"✓ Door {door_id} deleted successfully")
        return True, result
      else:
        error_msg = result.get('status_string', 'Unknown error') if result else 'No response'
        logger.error(f"✗ Failed to delete door {door_id}: {error_msg}")
        return False, {'error': error_msg}
        
    except Exception as e:
      logger.error(f"✗ Error deleting door {door_id}: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}

  def get_access_points(self):
    """Get all access points for door assignment (thread-safe)"""
    logger.info("=== GETTING ACCESS POINTS ===")
    try:
      auth_state = self.get_auth_state()
      logger.debug(f"Auth state for access points: {auth_state}")
      
      if not auth_state['connected']:
        logger.error("✗ WebSocket not connected")
        return []
      
      if not auth_state['authenticated']:
        logger.error("✗ Not authenticated")
        return []
      
      # Send access point list request
      logger.debug("Sending access_point.read request with access_point_id=0")
      result = self._run_in_websocket_thread('access_point.read', {'access_point_id': 0})
      
      logger.debug(f"Access points read result: {result}")
      
      if result and 'data' in result:
        access_points_data = result.get('data', [])
        logger.info(f"✓ Retrieved {len(access_points_data)} access points")
        logger.debug(f"Raw access points data: {access_points_data}")
        return access_points_data
      else:
        error_msg = result.get('status_string', 'Unknown error') if result else 'No response'
        logger.error(f"✗ Failed to get access points: {error_msg}")
        logger.error(f"Full error result: {result}")
        return []
        
    except Exception as e:
      logger.error(f"✗ Error getting access points: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return []

  def get_access_point(self, access_point_id):
    """Get a specific access point by ID (thread-safe)"""
    logger.info(f"=== GETTING ACCESS POINT {access_point_id} ===")
    try:
      auth_state = self.get_auth_state()
      logger.debug(f"Auth state for access point {access_point_id}: {auth_state}")
      
      if not auth_state['connected']:
        logger.error("✗ WebSocket not connected")
        return None
      
      if not auth_state['authenticated']:
        logger.error("✗ Not authenticated")
        return None
      
      # Send access point read request
      logger.debug(f"Sending access_point.read request with access_point_id={access_point_id}")
      result = self._run_in_websocket_thread('access_point.read', {'access_point_id': access_point_id})
      
      logger.debug(f"Access point {access_point_id} read result: {result}")
      
      if result and 'data' in result:
        access_point_data = result.get('data')
        if isinstance(access_point_data, list) and len(access_point_data) > 0:
          access_point_data = access_point_data[0]
        elif not access_point_data:
          logger.warning(f"✗ Access point {access_point_id} not found (empty data)")
          return None
        
        logger.info(f"✓ Retrieved access point {access_point_id}")
        logger.debug(f"Raw access point data: {access_point_data}")
        return access_point_data
      else:
        error_msg = result.get('status_string', 'Unknown error') if result else 'No response'
        logger.error(f"✗ Failed to get access point {access_point_id}: {error_msg}")
        logger.error(f"Full error result: {result}")
        return None
        
    except Exception as e:
      logger.error(f"✗ Error getting access point {access_point_id}: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return None

  def create_access_point(self, access_point_data):
    """Create a new access point (thread-safe)"""
    logger.info("=== CREATING ACCESS POINT ===")
    try:
      auth_state = self.get_auth_state()
      if not auth_state['connected']:
        logger.error("✗ WebSocket not connected")
        return False, {'error': 'WebSocket not connected'}
      
      if not auth_state['authenticated']:
        logger.error("✗ Not authenticated")
        return False, {'error': 'Not authenticated'}
      
      # Prepare access point attributes
      attributes = {
        'alias': access_point_data.get('alias', ''),
        'description': access_point_data.get('description', ''),
        'controller-module': access_point_data.get('controller_module', 'LEOSAC-BUILTIN-ACCESS-POINT')
      }
      
      # Send access point create request
      result = self._run_in_websocket_thread('access_point.create', {'attributes': attributes})
      
      if result and 'data' in result:
        logger.info("✓ Access point created successfully")
        return True, result.get('data', {})
      else:
        error_msg = result.get('status_string', 'Unknown error') if result else 'No response'
        logger.error(f"✗ Failed to create access point: {error_msg}")
        return False, {'error': error_msg}
        
    except Exception as e:
      logger.error(f"✗ Error creating access point: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}

  def update_access_point(self, access_point_id, access_point_data):
    """Update an existing access point (thread-safe)"""
    logger.info(f"=== UPDATING ACCESS POINT {access_point_id} ===")
    try:
      auth_state = self.get_auth_state()
      if not auth_state['connected']:
        logger.error("✗ WebSocket not connected")
        return False, {'error': 'WebSocket not connected'}
      
      if not auth_state['authenticated']:
        logger.error("✗ Not authenticated")
        return False, {'error': 'Not authenticated'}
      
      # Prepare access point attributes
      attributes = {}
      if 'alias' in access_point_data:
        attributes['alias'] = access_point_data['alias']
      if 'description' in access_point_data:
        attributes['description'] = access_point_data['description']
      if 'controller_module' in access_point_data:
        attributes['controller-module'] = access_point_data['controller_module']
      
      # Send access point update request
      result = self._run_in_websocket_thread('access_point.update', {
        'access_point_id': access_point_id,
        'attributes': attributes
      })
      
      if result and 'data' in result:
        logger.info(f"✓ Access point {access_point_id} updated successfully")
        return True, result.get('data', {})
      else:
        error_msg = result.get('status_string', 'Unknown error') if result else 'No response'
        logger.error(f"✗ Failed to update access point {access_point_id}: {error_msg}")
        return False, {'error': error_msg}
        
    except Exception as e:
      logger.error(f"✗ Error updating access point {access_point_id}: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}

  def delete_access_point(self, access_point_id):
    """Delete an access point (thread-safe)"""
    logger.info(f"=== DELETING ACCESS POINT {access_point_id} ===")
    try:
      auth_state = self.get_auth_state()
      if not auth_state['connected']:
        logger.error("✗ WebSocket not connected")
        return False, {'error': 'WebSocket not connected'}
      
      if not auth_state['authenticated']:
        logger.error("✗ Not authenticated")
        return False, {'error': 'Not authenticated'}
      
      # Send access point delete request
      result = self._run_in_websocket_thread('access_point.delete', {'access_point_id': access_point_id})
      
      if result is not None:  # Delete operations typically return None on success
        logger.info(f"✓ Access point {access_point_id} deleted successfully")
        return True, result
      else:
        error_msg = result.get('status_string', 'Unknown error') if result else 'No response'
        logger.error(f"✗ Failed to delete access point {access_point_id}: {error_msg}")
        return False, {'error': error_msg}
        
    except Exception as e:
      logger.error(f"✗ Error deleting access point {access_point_id}: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}

  # Wiegand Reader Methods
  def get_wiegand_readers(self):
    """Get all Wiegand readers (thread-safe)"""
    logger.info("=== GETTING WIEGAND READERS ===")
    try:
      auth_state = self.get_auth_state()
      logger.debug(f"Auth state for Wiegand readers: {auth_state}")
      
      if not auth_state['connected']:
        logger.error("✗ WebSocket not connected")
        return []
      
      if not auth_state['authenticated']:
        logger.error("✗ Not authenticated")
        return []
      
      # Send Wiegand reader list request
      logger.debug("Sending wiegand-reader.read request with reader_id=0")
      result = self._run_in_websocket_thread('wiegand-reader.read', {'reader_id': 0})
      
      logger.debug(f"Wiegand readers read result: {result}")
      
      if result and 'data' in result:
        wiegand_readers_data = result.get('data', [])
        logger.info(f"✓ Retrieved {len(wiegand_readers_data)} Wiegand readers")
        logger.debug(f"Raw Wiegand readers data: {wiegand_readers_data}")
        return wiegand_readers_data
      else:
        error_msg = result.get('status_string', 'Unknown error') if result else 'No response'
        logger.error(f"✗ Failed to get Wiegand readers: {error_msg}")
        logger.error(f"Full error result: {result}")
        return []
        
    except Exception as e:
      logger.error(f"✗ Error getting Wiegand readers: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return []

  def get_wiegand_reader(self, reader_id):
    """Get a specific Wiegand reader by ID (thread-safe)"""
    logger.info(f"=== GETTING WIEGAND READER {reader_id} ===")
    try:
      auth_state = self.get_auth_state()
      logger.debug(f"Auth state for Wiegand reader {reader_id}: {auth_state}")
      
      if not auth_state['connected']:
        logger.error("✗ WebSocket not connected")
        return None
      
      if not auth_state['authenticated']:
        logger.error("✗ Not authenticated")
        return None
      
      # Send Wiegand reader read request
      logger.debug(f"Sending wiegand-reader.read request with reader_id={reader_id}")
      result = self._run_in_websocket_thread('wiegand-reader.read', {'reader_id': reader_id})
      
      logger.debug(f"Wiegand reader {reader_id} read result: {result}")
      
      if result and 'data' in result:
        wiegand_reader_data = result.get('data')
        if isinstance(wiegand_reader_data, list) and len(wiegand_reader_data) > 0:
          wiegand_reader_data = wiegand_reader_data[0]
        elif not wiegand_reader_data:
          logger.warning(f"✗ Wiegand reader {reader_id} not found (empty data)")
          return None
        
        logger.info(f"✓ Retrieved Wiegand reader {reader_id}")
        logger.debug(f"Raw Wiegand reader data: {wiegand_reader_data}")
        return wiegand_reader_data
      else:
        error_msg = result.get('status_string', 'Unknown error') if result else 'No response'
        logger.error(f"✗ Failed to get Wiegand reader {reader_id}: {error_msg}")
        logger.error(f"Full error result: {result}")
        return None
        
    except Exception as e:
      logger.error(f"✗ Error getting Wiegand reader {reader_id}: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return None

  def create_wiegand_reader(self, wiegand_reader_data):
    """Create a new Wiegand reader (thread-safe)"""
    logger.info("=== CREATING WIEGAND READER ===")
    try:
      auth_state = self.get_auth_state()
      if not auth_state['connected']:
        logger.error("✗ WebSocket not connected")
        return False, {'error': 'WebSocket not connected'}
      
      if not auth_state['authenticated']:
        logger.error("✗ Not authenticated")
        return False, {'error': 'Not authenticated'}
      
      # Prepare Wiegand reader attributes
      attributes = {
        'alias': wiegand_reader_data.get('alias', ''),
        'description': wiegand_reader_data.get('description', ''),
        'mode': wiegand_reader_data.get('mode', 'SIMPLE_WIEGAND'),
        'pin_timeout': wiegand_reader_data.get('pin_timeout', 2500),
        'pin_key_end': wiegand_reader_data.get('pin_key_end', '#')
      }
      
      # Add hardware device IDs if provided
      if wiegand_reader_data.get('gpio_high_id'):
        attributes['gpio_high_id'] = wiegand_reader_data['gpio_high_id']
      if wiegand_reader_data.get('gpio_low_id'):
        attributes['gpio_low_id'] = wiegand_reader_data['gpio_low_id']
      if wiegand_reader_data.get('green_led_id'):
        attributes['green_led_id'] = wiegand_reader_data['green_led_id']
      if wiegand_reader_data.get('buzzer_id'):
        attributes['buzzer_id'] = wiegand_reader_data['buzzer_id']
      
      # Send Wiegand reader create request
      result = self._run_in_websocket_thread('wiegand-reader.create', {'attributes': attributes})
      
      if result and 'data' in result:
        logger.info("✓ Wiegand reader created successfully")
        return True, result.get('data', {})
      else:
        error_msg = result.get('status_string', 'Unknown error') if result else 'No response'
        logger.error(f"✗ Failed to create Wiegand reader: {error_msg}")
        return False, {'error': error_msg}
        
    except Exception as e:
      logger.error(f"✗ Error creating Wiegand reader: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}

  def update_wiegand_reader(self, reader_id, wiegand_reader_data):
    """Update an existing Wiegand reader (thread-safe)"""
    logger.info(f"=== UPDATING WIEGAND READER {reader_id} ===")
    try:
      auth_state = self.get_auth_state()
      if not auth_state['connected']:
        logger.error("✗ WebSocket not connected")
        return False, {'error': 'WebSocket not connected'}
      
      if not auth_state['authenticated']:
        logger.error("✗ Not authenticated")
        return False, {'error': 'Not authenticated'}
      
      # Prepare Wiegand reader attributes
      attributes = {}
      if 'alias' in wiegand_reader_data:
        attributes['alias'] = wiegand_reader_data['alias']
      if 'description' in wiegand_reader_data:
        attributes['description'] = wiegand_reader_data['description']
      if 'mode' in wiegand_reader_data:
        attributes['mode'] = wiegand_reader_data['mode']
      if 'pin_timeout' in wiegand_reader_data:
        attributes['pin_timeout'] = wiegand_reader_data['pin_timeout']
      if 'pin_key_end' in wiegand_reader_data:
        attributes['pin_key_end'] = wiegand_reader_data['pin_key_end']
      if 'gpio_high_id' in wiegand_reader_data:
        attributes['gpio_high_id'] = wiegand_reader_data['gpio_high_id']
      if 'gpio_low_id' in wiegand_reader_data:
        attributes['gpio_low_id'] = wiegand_reader_data['gpio_low_id']
      if 'green_led_id' in wiegand_reader_data:
        attributes['green_led_id'] = wiegand_reader_data['green_led_id']
      if 'buzzer_id' in wiegand_reader_data:
        attributes['buzzer_id'] = wiegand_reader_data['buzzer_id']
      
      # Send Wiegand reader update request
      result = self._run_in_websocket_thread('wiegand-reader.update', {
        'reader_id': reader_id,
        'attributes': attributes
      })
      
      if result and 'data' in result:
        logger.info(f"✓ Wiegand reader {reader_id} updated successfully")
        return True, result.get('data', {})
      else:
        error_msg = result.get('status_string', 'Unknown error') if result else 'No response'
        logger.error(f"✗ Failed to update Wiegand reader {reader_id}: {error_msg}")
        return False, {'error': error_msg}
        
    except Exception as e:
      logger.error(f"✗ Error updating Wiegand reader {reader_id}: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}

  def delete_wiegand_reader(self, reader_id):
    """Delete a Wiegand reader (thread-safe)"""
    logger.info(f"=== DELETING WIEGAND READER {reader_id} ===")
    try:
      auth_state = self.get_auth_state()
      if not auth_state['connected']:
        logger.error("✗ WebSocket not connected")
        return False, {'error': 'WebSocket not connected'}
      
      if not auth_state['authenticated']:
        logger.error("✗ Not authenticated")
        return False, {'error': 'Not authenticated'}
      
      # Send Wiegand reader delete request
      result = self._run_in_websocket_thread('wiegand-reader.delete', {'reader_id': reader_id})
      
      if result is not None:  # Delete operations typically return None on success
        logger.info(f"✓ Wiegand reader {reader_id} deleted successfully")
        return True, result
      else:
        error_msg = result.get('status_string', 'Unknown error') if result else 'No response'
        logger.error(f"✗ Failed to delete Wiegand reader {reader_id}: {error_msg}")
        return False, {'error': error_msg}
        
    except Exception as e:
      logger.error(f"✗ Error deleting Wiegand reader {reader_id}: {e}")
      logger.error(f"Traceback: {traceback.format_exc()}")
      return False, {'error': str(e)}

leosac_client = LeosacWebSocketService()