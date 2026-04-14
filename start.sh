#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Start the Crypto Swing Trader locally with a single command
# Usage: bash start.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create .env from example if missing
if [ ! -f .env ]; then
  echo "⚙️  Creating .env from .env.example — please fill in your API keys"
  cp .env.example .env
fi

# Create virtual environment if missing
if [ ! -d .venv ]; then
  echo "🐍 Creating Python virtual environment..."
  python3 -m venv .venv
fi

# Install/update dependencies
echo "📦 Installing dependencies..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

echo ""
echo "🚀 Starting Crypto Swing Trader..."
echo "   UI:      http://localhost:8001"
echo "   API:     http://localhost:8001/docs"
echo "   Health:  http://localhost:8001/health"
echo ""

.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
