#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Starting CryptoOSINT Backend on http://localhost:8000"
cd "$DIR/backend"

# activate venv if present
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# prefer python3 (macOS/Linux typically lack a bare `python`)
PYTHON_BIN="python3"
command -v python3 >/dev/null 2>&1 || PYTHON_BIN="python"

# Watch both backend/ and the bundled python-modules/ so edits to the
# intelligence engines (crypto_osint, etc.) trigger a live reload too.
"$PYTHON_BIN" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload \
    --reload-dir "$DIR/backend" --reload-dir "$DIR/python-modules"
