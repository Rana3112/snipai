#!/usr/bin/env bash
# SnipAI installer for macOS/Linux — currently Windows-only
# This script exists so `npm install -g snippai` doesn't fail on non-Windows.
# It just prints a notice and exits.

set -e

echo ""
echo "  SnipAI — AI Screen Assistant"
echo "  https://github.com/Rana3112/snipai"
echo ""
echo "  SnipAI is currently Windows 10/11 only (uses Win32 RegisterHotKey + mss)."
echo ""
echo "  On Windows, run one of:"
echo "    npm i -g snippai && snippai"
echo "    npx snippai"
echo "    powershell -ExecutionPolicy Bypass -c \"irm https://raw.githubusercontent.com/Rana3112/snipai/main/install.ps1 | iex\""
echo ""
echo "  On macOS/Linux, you can still use the backend (FastAPI) locally:"
echo "    git clone https://github.com/Rana3112/snipai.git && cd snipai"
echo "    pip install -r requirements.txt && python -m snipai  # will show tray error on non-Windows"
echo "    cd backend && pip install -r requirements.txt && uvicorn main:app --reload --port 8000"
echo ""
