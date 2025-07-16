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

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Configuration
LEOSAC_ADDR = os.environ.get('LEOSAC_ADDR', 'ws://localhost:8888')
WEBSOCKET_URL = f"{LEOSAC_ADDR}/websocket"

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

class LeosacWebSocketClient:
    def __init__(self):
        self.websocket = None
        self.connected = False
        self.callbacks = {}
        self.auth_token = None
        self.user_info = None
        self.loop = None
        
    async def connect(self):
        """Connect to Leosac WebSocket server"""
        try:
            self.websocket = await websockets.connect(WEBSOCKET_URL)
            self.connected = True
            self.loop = asyncio.get_event_loop()
            print(f"Connected to Leosac server at {WEBSOCKET_URL}")
            
            # Start listening for messages
            asyncio.create_task(self._listen_for_messages())
            return True
        except Exception as e:
            print(f"Failed to connect to Leosac server: {e}")
            self.connected = False
            return False
    
    async def _listen_for_messages(self):
        """Listen for incoming WebSocket messages"""
        try:
            async for message in self.websocket:
                await self._handle_message(message)
        except websockets.exceptions.ConnectionClosed:
            print("WebSocket connection closed")
            self.connected = False
        except Exception as e:
            print(f"Error in message listener: {e}")
            self.connected = False
    
    async def _handle_message(self, message):
        """Handle incoming WebSocket message"""
        try:
            data = json.loads(message)
            message_uuid = data.get('uuid')
            
            print(f"Received message with UUID: {message_uuid}, type: {data.get('type')}, status_code: {data.get('status_code')}")
            
            if message_uuid in self.callbacks:
                callback = self.callbacks[message_uuid]
                if data.get('status_code') == 0:
                    # Success - pass the full response object, not just content
                    callback['success'](data)
                else:
                    # Error
                    callback['error'](data)
                del self.callbacks[message_uuid]
            else:
                # Handle opportunistic messages (like session_closed)
                if data.get('type') == 'session_closed':
                    print(f"Session closed: {data.get('content', {}).get('reason', 'Unknown reason')}")
                    self.auth_token = None
                    self.user_info = None
        except json.JSONDecodeError as e:
            print(f"Failed to parse message: {e}")
    
    async def send_json(self, command, content):
        """Send JSON message to Leosac server"""
        if not self.connected:
            # Try to connect if not connected
            print("WebSocket not connected, attempting to connect...")
            await self.connect()
            if not self.connected:
                raise Exception("Failed to connect to Leosac server")
        
        message_uuid = str(uuid.uuid4())
        message = {
            'uuid': message_uuid,
            'type': command,
            'content': content
        }
        
        print(f"Sending message: {command} with UUID: {message_uuid}")
        
        # Create a promise-like structure
        future = asyncio.Future()
        
        def on_success(data):
            if not future.done():
                print(f"Success callback for {message_uuid}: {data}")
                future.set_result(data)
        
        def on_error(error):
            if not future.done():
                print(f"Error callback for {message_uuid}: {error}")
                future.set_exception(Exception(f"Leosac error: {error.get('status_string', 'Unknown error')}"))
        
        self.callbacks[message_uuid] = {
            'success': on_success,
            'error': on_error
        }
        
        await self.websocket.send(json.dumps(message))
        return await future
    
    async def authenticate(self, username, password):
        """Authenticate with username and password"""
        try:
            result = await self.send_json('create_auth_token', {
                'username': username,
                'password': password
            })
            
            # Check if authentication was successful
            if result.get('status_code') == 0:
                content = result.get('content', {})
                self.auth_token = content.get('token')
                self.user_info = {
                    'user_id': content.get('user_id'),
                    'username': username
                }
                return True, result
            else:
                return False, result
        except Exception as e:
            return False, {'error': str(e)}
    
    async def authenticate_with_token(self, token):
        """Authenticate with stored token"""
        try:
            result = await self.send_json('authenticate_with_token', {
                'token': token
            })
            
            if result.get('status_code') == 0:
                content = result.get('content', {})
                self.auth_token = token
                self.user_info = {
                    'user_id': content.get('user_id'),
                    'username': content.get('username')
                }
                return True, result
            else:
                return False, result
        except Exception as e:
            return False, {'error': str(e)}
    
    async def logout(self):
        """Logout from Leosac server"""
        try:
            await self.send_json('logout', {})
            self.auth_token = None
            self.user_info = None
            return True
        except Exception as e:
            print(f"Logout error: {e}")
            return False
    
    async def get_users(self):
        """Get all users"""
        try:
            result = await self.send_json('user.read', {'user_id': 0})
            if result.get('status_code') == 0:
                content = result.get('content', {})
                # Parse JSON:API format
                if 'data' in content and isinstance(content['data'], list):
                    users = []
                    for user_data in content['data']:
                        user = {
                            'id': user_data.get('id'),
                            **user_data.get('attributes', {})
                        }
                        users.append(user)
                    return users
                return []
            else:
                return []
        except Exception as e:
            print(f"Error getting users: {e}")
            return []
    
    async def get_user(self, user_id):
        """Get a specific user by ID"""
        try:
            result = await self.send_json('user.read', {'user_id': int(user_id)})
            if result.get('status_code') == 0:
                content = result.get('content', {})
                # Parse JSON:API format - single user returns object, not array
                if 'data' in content:
                    user_data = content['data']
                    # Handle both single user (object) and multiple users (array) responses
                    if isinstance(user_data, list):
                        if len(user_data) > 0:
                            user_data = user_data[0]
                        else:
                            return None
                    
                    user = {
                        'id': user_data.get('id'),
                        **user_data.get('attributes', {})
                    }
                    return user
                return None
            else:
                return None
        except Exception as e:
            print(f"Error getting user {user_id}: {e}")
            return None
    
    async def create_user(self, user_data):
        """Create a new user"""
        try:
            result = await self.send_json('user.create', {
                'attributes': user_data
            })
            return result.get('status_code') == 0, result
        except Exception as e:
            return False, {'error': str(e)}
    
    async def update_user(self, user_id, user_data):
        """Update an existing user"""
        try:
            result = await self.send_json('user.update', {
                'user_id': int(user_id),
                'attributes': user_data
            })
            return result.get('status_code') == 0, result
        except Exception as e:
            return False, {'error': str(e)}
    
    async def delete_user(self, user_id):
        """Delete a user"""
        try:
            result = await self.send_json('user.delete', {
                'user_id': int(user_id)
            })
            return result.get('status_code') == 0, result
        except Exception as e:
            return False, {'error': str(e)}

# Global WebSocket client
leosac_client = LeosacWebSocketClient()

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
        leosac_client.auth_token = auth_token
        leosac_client.user_info = user_info
        
        # Check if the WebSocket client state matches the session
        if (leosac_client.auth_token == auth_token and 
            leosac_client.user_info and 
            str(leosac_client.user_info.get('user_id')) == user_id):
            
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
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        print(f"Login attempt for username: {username}")
        
        if not username or not password:
            flash('Please provide both username and password', 'error')
            return render_template('login.html')
        
        import asyncio
        try:
            # Use the WebSocket client's event loop
            if hasattr(leosac_client, '_loop'):
                loop = leosac_client._loop
                # Use run_coroutine_threadsafe to communicate with the WebSocket client
                future = asyncio.run_coroutine_threadsafe(
                    leosac_client.authenticate(username, password), loop
                )
                success, result = future.result(timeout=5.0)
            else:
                # Fallback: create a new event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    success, result = loop.run_until_complete(leosac_client.authenticate(username, password))
                finally:
                    loop.close()
            
            print(f"Authentication result: success={success}, result={result}")
            
            if success:
                try:
                    print("Authentication successful, creating user object...")
                    user = LeosacUser(
                        leosac_client.user_info['user_id'],
                        leosac_client.user_info['username']
                    )
                    print(f"Creating user object: {user.username} (ID: {user.id})")
                    print(f"User info before login: {leosac_client.user_info}")
                    print(f"Auth token before login: {leosac_client.auth_token}")
                    
                    # Store authentication info in session
                    session['auth_token'] = leosac_client.auth_token
                    session['user_info'] = leosac_client.user_info
                    
                    print("About to call login_user...")
                    login_user(user)
                    print("login_user completed successfully")
                    
                    print(f"User authenticated: {current_user.is_authenticated}")
                    print(f"Current user: {current_user.username if current_user.is_authenticated else 'None'}")
                    print(f"Session stored: auth_token={bool(session.get('auth_token'))}, user_info={session.get('user_info')}")
                    
                    flash(f'Welcome {username}!', 'success')
                    print("About to redirect to index...")
                    return redirect(url_for('index'))
                except Exception as e:
                    print(f"Exception in login success block: {e}")
                    import traceback
                    traceback.print_exc()
                    flash(f'Login error: {str(e)}', 'error')
                    return render_template('login.html')
            else:
                error_msg = result.get("message", result.get("error", "Unknown error"))
                print(f"Authentication failed: {error_msg}")
                flash(f'Authentication failed: {error_msg}', 'error')
        except Exception as e:
            print(f"Authentication exception: {e}")
            flash(f'Connection error: {str(e)}', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    print("Logout route called")
    
    # Use the WebSocket client's event loop for logout
    if hasattr(leosac_client, '_loop'):
        loop = leosac_client._loop
        # Use run_coroutine_threadsafe to communicate with the WebSocket client
        future = asyncio.run_coroutine_threadsafe(
            leosac_client.logout(), loop
        )
        try:
            future.result(timeout=5.0)
            print("WebSocket logout successful")
        except Exception as e:
            print(f"WebSocket logout error: {e}")
    else:
        # Fallback: create a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(leosac_client.logout())
            print("WebSocket logout successful (fallback)")
        except Exception as e:
            print(f"WebSocket logout error: {e}")
        finally:
            loop.close()
    
    # Clear session data
    session.pop('auth_token', None)
    session.pop('user_info', None)
    
    # Clear WebSocket client state
    leosac_client.auth_token = None
    leosac_client.user_info = None
    
    print("Session and client state cleared")
    
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/status')
def status():
    """Check WebSocket connection status"""
    return {
        'connected': leosac_client.connected,
        'server': LEOSAC_ADDR,
        'auth_token': bool(leosac_client.auth_token),
        'user_info': leosac_client.user_info
    }

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
        # Check if WebSocket client is connected
        if not leosac_client.connected or not leosac_client.loop:
            flash('WebSocket connection not available. Please try again.', 'error')
            return render_template('users/list.html', users=[])
        
        # Get users from WebSocket using the client's event loop
        future = asyncio.run_coroutine_threadsafe(leosac_client.get_users(), leosac_client.loop)
        users = future.result(timeout=10)
        
        return render_template('users/list.html', users=users)
    except Exception as e:
        flash(f'Error loading users: {str(e)}', 'error')
        return render_template('users/list.html', users=[])

@app.route('/users/create', methods=['GET', 'POST'])
@login_required
def users_create():
    """Create a new user"""
    if request.method == 'POST':
        try:
            # Check if WebSocket client is connected
            if not leosac_client.connected or not leosac_client.loop:
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
            future = asyncio.run_coroutine_threadsafe(leosac_client.create_user(user_data), leosac_client.loop)
            success, result = future.result(timeout=10)
            
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
        if not leosac_client.connected or not leosac_client.loop:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('users_list'))
        
        # Don't allow deleting the current user
        if user_id == current_user.id:
            flash('You cannot delete your own account', 'error')
            return redirect(url_for('users_list'))
        
        # Delete user via WebSocket
        future = asyncio.run_coroutine_threadsafe(leosac_client.delete_user(user_id), leosac_client.loop)
        success, result = future.result(timeout=10)
        
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
        if not leosac_client.connected or not leosac_client.loop:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('users_list'))
        
        # Get user details from WebSocket
        future = asyncio.run_coroutine_threadsafe(leosac_client.get_user(user_id), leosac_client.loop)
        user = future.result(timeout=10)
        
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

def start_websocket_client():
    """Start WebSocket client in background thread"""
    def run_client():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Store the loop reference in the client
        leosac_client._loop = loop
        
        async def client_loop():
            while True:
                try:
                    if not leosac_client.connected:
                        await leosac_client.connect()
                    await asyncio.sleep(1)
                except Exception as e:
                    print(f"WebSocket client error: {e}")
                    await asyncio.sleep(5)  # Wait before retrying
        
        loop.run_until_complete(client_loop())
    
    thread = threading.Thread(target=run_client, daemon=True)
    thread.start()

if __name__ == '__main__':
    # Start WebSocket client
    start_websocket_client()
    
    # Give some time for initial connection
    time.sleep(3)
    
    # Check if connection was established
    if leosac_client.connected:
        print("✓ WebSocket client connected successfully")
    else:
        print("⚠ WebSocket client not connected, will attempt connection on first request")
    
    app.run(debug=True, host='0.0.0.0', port=5000) 