@echo off
echo ==========================================================
echo  VIGIL-CHAIN: AI-Powered Bitcoin Traffic Intelligence
echo  National Technical Research Organisation (NTRO) - SIH 2026
echo  (Running in 100% Air-Gapped Offline Mode)
echo ==========================================================

python -m src.pipeline.engine
if %errorlevel% neq 0 (
    echo [!] Pipeline failed. Check dependencies.
    pause
    exit /b %errorlevel%
)

echo [*] Launching Offline Analyst Dashboard at http://127.0.0.1:8000
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
pause
