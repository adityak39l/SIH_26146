#!/usr/bin/env bash
# SIH26146: VIGIL-CHAIN Offline Launcher for Linux
set -e

echo "=========================================================="
echo " VIGIL-CHAIN: AI-Powered Bitcoin Traffic Intelligence"
echo " National Technical Research Organisation (NTRO) - SIH 2026"
echo " (Running in 100% Air-Gapped Offline Mode)"
echo "=========================================================="

# Check Python environment
if ! command -v python3 &> /dev/null; then
    echo "[!] Python3 not found. Please install Python 3.10+."
    exit 1
fi

echo "[*] Initializing offline pipeline demo..."
python3 -m src.pipeline.engine

echo "[*] Launching Offline Analyst Dashboard & API at http://127.0.0.1:8000"
uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
