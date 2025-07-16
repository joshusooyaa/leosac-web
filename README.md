# Leosac Web GUI - Flask Version

This is a Flask-based web interface for the Leosac access control system. It provides a modern web interface to manage and monitor Leosac installations.

## Features

- **WebSocket Communication**: Direct communication with Leosac server via WebSocket protocol
- **User Authentication**: Secure login system using Leosac's authentication
- **Modern UI**: Bootstrap 5 based responsive interface
- **Real-time Connection**: Maintains persistent connection to Leosac server

## Prerequisites

- Python 3.8 or higher
- A running Leosac server with WebSocket support
- Network access to the Leosac server

## Installation

1. Clone or download this project
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy the environment example and configure it:
   ```bash
   cp env.example .env
   ```

4. Edit `.env` file with your Leosac server details:
   ```
   LEOSAC_ADDR=ws://your-leosac-server:8888
   SECRET_KEY=your-secret-key-here
   ```

## Usage

1. Start the Flask application:
   ```bash
   python app.py
   ```

2. Open your browser and navigate to `http://localhost:5000`

3. Login with your Leosac credentials

## Configuration

### Environment Variables

- `LEOSAC_ADDR`: WebSocket address of your Leosac server (e.g., `ws://192.168.1.100:8888`)
- `SECRET_KEY`: Flask secret key for session management
- `FLASK_DEBUG`: Set to `True` for development mode

### Leosac Server Connection

The application will automatically:
- Connect to the Leosac server on startup
- Maintain a persistent WebSocket connection
- Reconnect automatically if the connection is lost
- Handle authentication tokens

## Development

This Flask application replicates the functionality of the original Ember.js application but with a simpler, more maintainable codebase. The WebSocket communication protocol remains the same to ensure compatibility with existing Leosac servers.

### Project Structure

```
leosac-web/
├── app.py              # Main Flask application
├── requirements.txt    # Python dependencies
├── templates/          # HTML templates
│   ├── base.html      # Base template
│   ├── login.html     # Login page
│   └── index.html     # Dashboard
├── env.example        # Environment configuration example
└── README.md          # This file
```

## Security Notes

- Change the `SECRET_KEY` in production
- Use HTTPS in production environments
- Ensure proper network security for Leosac server communication
- Consider implementing rate limiting for login attempts

## Troubleshooting

### Connection Issues

If you can't connect to the Leosac server:

1. Verify the `LEOSAC_ADDR` is correct
2. Check if the Leosac server is running and accessible
3. Ensure firewall rules allow WebSocket connections
4. Check the console output for connection error messages

### Authentication Issues

If login fails:

1. Verify your Leosac credentials
2. Check if the Leosac server supports the authentication protocol
3. Review server logs for authentication errors

## License

This project follows the same license as the original Leosac Web GUI. 