#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Starting CryptoOSINT Frontend on http://localhost:5173"
cd "$DIR/frontend"
npm run dev
