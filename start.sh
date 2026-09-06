#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# kill both processes when this script exits (Ctrl+C, close terminal, etc.)
cleanup() {
    echo ""
    echo "Stopping CryptoOSINT..."
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null
    wait 2>/dev/null
}
trap cleanup EXIT INT TERM

# --- backend ---
echo "Starting CryptoOSINT Backend on http://localhost:8000"
(
    cd "$DIR/backend"

    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    elif [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    fi

    PYTHON_BIN="python3"
    command -v python3 >/dev/null 2>&1 || PYTHON_BIN="python"

    exec "$PYTHON_BIN" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload \
        --reload-dir "$DIR/backend" --reload-dir "$DIR/python-modules"
) &
BACKEND_PID=$!

# --- frontend ---
echo "Starting CryptoOSINT Frontend on http://localhost:5173"
(
    cd "$DIR/frontend"
    exec npm run dev
) &
FRONTEND_PID=$!

echo ""
echo "Both servers are running. Press Ctrl+C to stop."
wait
