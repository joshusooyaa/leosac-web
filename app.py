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

class LeosacWebSocketClient:
    def __init__(self):
        self.websocket = None
        self.connected = False
        self.callbacks = {}
        self.auth_token = None
        self.user_info = None
        
    async def connect(self):
        """Connect to Leosac WebSocket server"""
        try:
            self.websocket = await websockets.connect(WEBSOCKET_URL)
            self.connected = True
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
            
            if message_uuid in self.callbacks:
                callback = self.callbacks[message_uuid]
                if data.get('status_code') == 0:
                    # Success
                    callback['success'](data.get('content', {}))
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
        
        # Create a promise-like structure
        future = asyncio.Future()
        
        def on_success(data):
            if not future.done():
                future.set_result(data)
        
        def on_error(error):
            if not future.done():
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
            if result.get('status') == 0:
                self.auth_token = result.get('token')
                self.user_info = {
                    'user_id': result.get('user_id'),
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
            
            if result.get('status') == 0:
                self.auth_token = token
                self.user_info = {
                    'user_id': result.get('user_id'),
                    'username': result.get('username')
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

# Global WebSocket client
leosac_client = LeosacWebSocketClient()

@login_manager.user_loader
def load_user(user_id):
    if leosac_client.user_info and str(leosac_client.user_info['user_id']) == user_id:
        return LeosacUser(
            leosac_client.user_info['user_id'],
            leosac_client.user_info['username']
        )
    return None

@app.route('/')
@login_required
def index():
    return render_template('index.html', user=current_user, config={'LEOSAC_ADDR': LEOSAC_ADDR})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash('Please provide both username and password', 'error')
            return render_template('login.html')
        
        # Run authentication in async context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            success, result = loop.run_until_complete(leosac_client.authenticate(username, password))
            
            print(f"Authentication result: success={success}, result={result}")
            
            if success:
                user = LeosacUser(
                    leosac_client.user_info['user_id'],
                    leosac_client.user_info['username']
                )
                login_user(user)
                flash(f'Welcome {username}!', 'success')
                return redirect(url_for('index'))
            else:
                error_msg = result.get("message", "Unknown error")
                print(f"Authentication failed: {error_msg}")
                flash(f'Authentication failed: {error_msg}', 'error')
        except Exception as e:
            print(f"Authentication exception: {e}")
            flash(f'Connection error: {str(e)}', 'error')
        finally:
            loop.close()
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    # Run logout in async context
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(leosac_client.logout())
    except Exception as e:
        print(f"Logout error: {e}")
    finally:
        loop.close()
    
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

def start_websocket_client():
    """Start WebSocket client in background thread"""
    def run_client():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
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