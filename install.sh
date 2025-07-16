#!/bin/bash

echo "Leosac Web GUI - Flask Installation"
echo "==================================="

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    exit 1
fi

# Check Python version
python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
required_version="3.8"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
    echo "Error: Python 3.8 or higher is required. Found: $python_version"
    exit 1
fi

echo "✓ Python $python_version found"

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cp env.example .env
    echo "✓ .env file created. Please edit it with your Leosac server details."
else
    echo "✓ .env file already exists"
fi

echo ""
echo "Installation complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env file with your Leosac server address"
echo "2. Activate virtual environment: source venv/bin/activate"
echo "3. Test connection: python test_connection.py"
echo "4. Start application: python run.py"
echo ""
echo "For more information, see README.md" 