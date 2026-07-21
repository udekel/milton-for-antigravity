#!/bin/bash
# Local runner for Milton Agent Server
export MILTON_HOST=${MILTON_HOST:-"127.0.0.1"}
export MILTON_PORT=${MILTON_PORT:-"8000"}

echo "🚀 Starting Milton Agent Backend locally on http://${MILTON_HOST}:${MILTON_PORT}..."
python3 -m uvicorn app.main:app --host ${MILTON_HOST} --port ${MILTON_PORT} --reload
