#!/usr/bin/env bash
# SIH26146: VIGIL-CHAIN Offline Launcher for Linux
set -e

echo "=========================================================="
echo " VIGIL-CHAIN: AI-Powered Bitcoin Traffic Intelligence"
echo " SIH 2026 - Problem Statement 26146"
echo " (Running in 100% Air-Gapped Offline Mode)"
echo "=========================================================="

# Check Python environment
if ! command -v python3 &> /dev/null; then
    echo "[!] Python3 not found. Please install Python 3.10+."
    exit 1
fi

echo "[*] Running offline pipeline on data/raw/demo ..."
python3 -m src.pipeline.engine

echo "[*] Building standalone analyst console (docs/index.html) ..."
python3 -m src.pipeline.export

echo "[*] Launching Offline Analyst Console & API at http://127.0.0.1:8000"
python3 -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
