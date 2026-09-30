@echo off
echo ==========================================================
echo  VIGIL-CHAIN: AI-Powered Bitcoin Traffic Intelligence
echo  SIH 2026 - Problem Statement 26146
echo  (Running in 100%% Air-Gapped Offline Mode)
echo ==========================================================

python -m src.pipeline.engine
if %errorlevel% neq 0 (
    echo [!] Pipeline failed. Check dependencies: pip install -r requirements.txt
    pause
    exit /b %errorlevel%
)

echo [*] Building standalone analyst console (docs\index.html) ...
python -m src.pipeline.export

echo [*] Launching Offline Analyst Console at http://127.0.0.1:8000
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
pause
