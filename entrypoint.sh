#!/bin/bash
# =============================================================
# Single-container entrypoint for Render free tier.
# Runs both FastAPI (web) and ARQ (worker) in one container.
# =============================================================

set -e

echo "🚀 Starting Wickham Roofing AI Orchestrator..."

# Start ARQ worker in the background
echo "⚙️  Starting ARQ worker..."
arq app.workers.settings.WorkerSettings &
ARQ_PID=$!

# Start FastAPI in the foreground
echo "🌐 Starting FastAPI server on port ${PORT:-8000}..."
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"

# If uvicorn exits, kill the ARQ worker too
kill $ARQ_PID 2>/dev/null
