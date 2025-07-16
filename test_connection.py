#!/usr/bin/env python3
"""
Simple test script to verify WebSocket connection to Leosac server
"""

import asyncio
import websockets
import json
import os
from dotenv import load_dotenv

load_dotenv()

LEOSAC_ADDR = os.environ.get('LEOSAC_ADDR', 'ws://localhost:8888')
WEBSOCKET_URL = f"{LEOSAC_ADDR}/websocket"

async def test_connection():
    """Test basic WebSocket connection to Leosac server"""
    try:
        print(f"Attempting to connect to {WEBSOCKET_URL}...")
        
        async with websockets.connect(WEBSOCKET_URL) as websocket:
            print("✓ Successfully connected to Leosac server!")
            
            # Test a simple message
            test_message = {
                'uuid': 'test-123',
                'type': 'get_leosac_version',
                'content': {}
            }
            
            print("Sending test message...")
            await websocket.send(json.dumps(test_message))
            
            # Wait for response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                data = json.loads(response)
                print(f"✓ Received response: {data}")
            except asyncio.TimeoutError:
                print("⚠ No response received within 5 seconds")
            
    except websockets.exceptions.InvalidURI:
        print(f"✗ Invalid WebSocket URI: {WEBSOCKET_URL}")
        print("Make sure LEOSAC_ADDR is in the format: ws://hostname:port")
    except websockets.exceptions.ConnectionRefused:
        print(f"✗ Connection refused to {WEBSOCKET_URL}")
        print("Make sure the Leosac server is running and accessible")
    except Exception as e:
        print(f"✗ Connection failed: {e}")

if __name__ == "__main__":
    print("Leosac WebSocket Connection Test")
    print("=" * 40)
    print(f"Server: {LEOSAC_ADDR}")
    print()
    
    asyncio.run(test_connection()) 