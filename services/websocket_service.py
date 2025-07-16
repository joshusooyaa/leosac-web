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
                        'validity_enabled': user_data.get('attributes', {}).get('validity_enabled', False),
                        'validity_start': user_data.get('attributes', {}).get('validity_start'),
                        'validity_end': user_data.get('attributes', {}).get('validity_end'),
                        'version': user_data.get('attributes', {}).get('version', 0)
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
                    'validity_enabled': user_data.get('attributes', {}).get('validity_enabled', False),
                    'validity_start': user_data.get('attributes', {}).get('validity_start'),
                    'validity_end': user_data.get('attributes', {}).get('validity_end'),
                    'version': user_data.get('attributes', {}).get('version', 0)
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
            result = self._run_in_websocket_thread('credential.read', {'owner_id': int(user_id)})
            
            if result and 'data' in result:
                credentials = []
                for cred_data in result['data']:
                    credential = {
                        'id': cred_data.get('id'),
                        'alias': cred_data.get('attributes', {}).get('alias'),
                        'description': cred_data.get('attributes', {}).get('description'),
                        'type': cred_data.get('type'),
                        'validity_enabled': cred_data.get('attributes', {}).get('validity_enabled', False),
                        'validity_start': cred_data.get('attributes', {}).get('validity_start'),
                        'validity_end': cred_data.get('attributes', {}).get('validity_end'),
                        'version': cred_data.get('attributes', {}).get('version', 0)
                    }
                    credentials.append(credential)
                logger.info(f"✓ Retrieved {len(credentials)} credentials for user {user_id}")
                return credentials
            logger.warning(f"✗ No credentials found for user {user_id}")
            return []
        except Exception as e:
            logger.error(f"✗ Error getting user credentials for {user_id}: {e}")
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

# Global WebSocket client instance
leosac_client = LeosacWebSocketService() 