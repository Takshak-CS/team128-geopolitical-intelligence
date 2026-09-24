#!/bin/bash
cd "$(dirname "$0")"
echo "Starting backend..."
uvicorn backend.main:app --reload --port 8000 &
BACKEND_PID=$!
echo "Starting frontend..."
cd frontend && npm run dev &
FRONTEND_PID=$!
echo ""
echo "Backend:  http://localhost:8000"
echo "Frontend: http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop both."
wait
