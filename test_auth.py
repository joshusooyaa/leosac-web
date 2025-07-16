#!/usr/bin/env python3
"""
Test script to debug authentication with Leosac server
"""

import asyncio
import websockets
import json
import os
import uuid
from dotenv import load_dotenv

load_dotenv()

LEOSAC_ADDR = os.environ.get('LEOSAC_ADDR', 'ws://localhost:8888')
WEBSOCKET_URL = f"{LEOSAC_ADDR}/websocket"

async def test_authentication():
    """Test authentication with Leosac server"""
    try:
        print(f"Connecting to {WEBSOCKET_URL}...")
        
        async with websockets.connect(WEBSOCKET_URL) as websocket:
            print("✓ Connected to Leosac server!")
            
            # Test authentication
            username = input("Enter username: ")
            password = input("Enter password: ")
            
            message_uuid = str(uuid.uuid4())
            auth_message = {
                'uuid': message_uuid,
                'type': 'create_auth_token',
                'content': {
                    'username': username,
                    'password': password
                }
            }
            
            print(f"Sending authentication message: {json.dumps(auth_message, indent=2)}")
            await websocket.send(json.dumps(auth_message))
            
            # Wait for response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                data = json.loads(response)
                print(f"✓ Received response: {json.dumps(data, indent=2)}")
                
                # Check response structure
                print(f"\nResponse analysis:")
                print(f"- UUID: {data.get('uuid')}")
                print(f"- Type: {data.get('type')}")
                print(f"- Status Code: {data.get('status_code')}")
                print(f"- Status String: {data.get('status_string')}")
                print(f"- Content: {data.get('content')}")
                
                if data.get('status_code') == 0:
                    print("✓ Authentication successful!")
                    content = data.get('content', {})
                    print(f"- User ID: {content.get('user_id')}")
                    print(f"- Token: {content.get('token')}")
                    print(f"- Status: {content.get('status')}")
                else:
                    print(f"✗ Authentication failed: {data.get('status_string')}")
                    
            except asyncio.TimeoutError:
                print("⚠ No response received within 10 seconds")
            
    except websockets.exceptions.ConnectionRefused:
        print(f"✗ Connection refused to {WEBSOCKET_URL}")
    except Exception as e:
        print(f"✗ Error: {e}")

if __name__ == "__main__":
    print("Leosac Authentication Test")
    print("=" * 40)
    print(f"Server: {LEOSAC_ADDR}")
    print()
    
    asyncio.run(test_authentication()) 