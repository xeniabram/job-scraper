#!/bin/bash
set -e

echo "Setting up Job Scraper..."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "uv not found. Install it first: https://github.com/astral-sh/uv"
    exit 1
fi

# Check if Ollama is installed
if ! command -v ollama &> /dev/null; then
    echo "Ollama not found. Install it first: https://ollama.ai"
    exit 1
fi

# Install Python dependencies
echo "Installing dependencies..."
uv sync

# Install Playwright browsers
echo "Installing Playwright browsers..."
uv run playwright install chromium

# Setup .env file
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "Please edit .env with your credentials!"
else
    echo ".env already exists"
fi

# Create data and logs directories
mkdir -p data logs

# Check if Ollama is running and has a model
echo "Checking Ollama setup..."
if ollama list | grep -q llama3.2:latest; then
    echo "Ollama llama3.2:latest model found"
else
    echo "Downloading Ollama llama3.2:latest model (this may take a few minutes)..."
    ollama pull llama3.2:latest
fi

echo ""
echo "Setup complete"
echo ""
echo "Next steps:"
echo "1. Edit .env with your preferences"
echo "2. Edit config.yaml with your job preferences"
echo "3. Run: uv run job-scraper"
echo ""
