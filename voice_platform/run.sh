#!/bin/bash
# ============================================
# Voice Agent Platform — Run Script
# ============================================
# 
# This script starts the voice agent platform server.
# It handles PortAudio library path and launches uvicorn.
#
# Usage:
#   ./platform/run.sh              # Start with defaults
#   ./platform/run.sh --port 8000  # Custom port
#
# Prerequisites:
#   - Redis running (docker run -d --name vocode-redis -p 6379:6379 redis:7-alpine)
#   - .env file configured in platform/.env
#   - Poetry environment set up (poetry install --extras telephony)

set -e

# Navigate to project root
cd "$(dirname "$0")/.."

# Add PortAudio library to path (installed via conda)
export LD_LIBRARY_PATH="${HOME}/anaconda3/lib:${LD_LIBRARY_PATH:-}"

# Default port
PORT="${1:-3000}"

echo "============================================"
echo "🚀 Starting Voice Agent Platform"
echo "============================================"
echo "Port: $PORT"
echo "Redis: $(docker exec vocode-redis redis-cli ping 2>/dev/null || echo 'NOT RUNNING ⚠️')"
echo "============================================"
echo ""

# Start the server
poetry run uvicorn voice_platform.main:app --host 0.0.0.0 --port "$PORT" --reload
