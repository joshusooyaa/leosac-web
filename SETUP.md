# Leosac Web GUI - Flask Setup Guide

## Quick Start

1. **Install dependencies:**
   ```bash
   ./install.sh
   ```

2. **Configure your Leosac server:**
   ```bash
   # Edit the .env file
   nano .env
   ```
   
   Set your Leosac server address:
   ```
   LEOSAC_ADDR=ws://your-leosac-server:8888
   ```

3. **Test the connection:**
   ```bash
   source venv/bin/activate
   python test_connection.py
   ```

4. **Start the application:**
   ```bash
   python run.py
   ```

5. **Open your browser:**
   Navigate to `http://localhost:5000`

## Manual Installation

If you prefer to install manually:

1. **Create virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   ```bash
   cp env.example .env
   # Edit .env with your settings
   ```

4. **Run the application:**
   ```bash
   python run.py
   ```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LEOSAC_ADDR` | WebSocket address of Leosac server | `ws://localhost:8888` |
| `SECRET_KEY` | Flask secret key for sessions | `dev-secret-key-change-in-production` |
| `FLASK_DEBUG` | Enable Flask debug mode | `True` |

### Example .env file:
```
LEOSAC_ADDR=ws://192.168.1.100:8888
SECRET_KEY=your-super-secret-key-here
FLASK_DEBUG=True
```

## Troubleshooting

### Connection Issues

**Problem:** Can't connect to Leosac server
- Verify the server address in `.env`
- Check if Leosac server is running
- Test with `python test_connection.py`

**Problem:** WebSocket connection refused
- Check firewall settings
- Verify the port is correct (default: 8888)
- Ensure Leosac has WebSocket support enabled

### Authentication Issues

**Problem:** Login fails
- Verify your Leosac credentials
- Check server logs for authentication errors
- Ensure the user has proper permissions

### Application Issues

**Problem:** Flask app won't start
- Check if port 5000 is available
- Verify all dependencies are installed
- Check Python version (3.8+ required)

## Development

### Project Structure
```
leosac-web/
├── app.py              # Main Flask application
├── run.py              # Startup script
├── test_connection.py  # Connection test utility
├── requirements.txt    # Python dependencies
├── install.sh          # Installation script
├── .env                # Environment configuration
├── env.example         # Environment template
├── templates/          # HTML templates
│   ├── base.html      # Base template
│   ├── login.html     # Login page
│   └── index.html     # Dashboard
└── README.md          # Documentation
```

### Adding Features

The application is designed to be easily extensible:

1. **Add new routes** in `app.py`
2. **Create new templates** in `templates/`
3. **Extend WebSocket client** in the `LeosacWebSocketClient` class
4. **Add new Leosac commands** using the `send_json()` method

### WebSocket Protocol

The application uses the same WebSocket protocol as the original Ember.js application:

```json
{
  "uuid": "unique-message-id",
  "type": "command-name",
  "content": {
    "parameter1": "value1",
    "parameter2": "value2"
  }
}
```

Responses follow this format:
```json
{
  "uuid": "same-as-request",
  "status_code": 0,
  "status_string": "Success",
  "content": {
    "data": "response-data"
  }
}
```

## Security Considerations

1. **Change the SECRET_KEY** in production
2. **Use HTTPS** for production deployments
3. **Implement rate limiting** for login attempts
4. **Secure network access** to Leosac server
5. **Regular security updates** for dependencies

## Support

For issues and questions:
1. Check the troubleshooting section above
2. Review the original Leosac documentation
3. Check server logs for detailed error messages
4. Test with the connection utility first 