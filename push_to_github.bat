@echo off
echo ==========================================================
echo  Pushing VIGIL-CHAIN to GitHub
echo  Account: DIVINE039
echo ==========================================================
echo.

git remote remove origin 2>nul
git remote add origin https://github.com/DIVINE039/sih26146-vigil-chain.git
git branch -M main

echo [*] Pushing main branch to https://github.com/DIVINE039/sih26146-vigil-chain.git ...
git push -u origin main

if %errorlevel% equ 0 (
    echo.
    echo ==========================================================
    echo  [SUCCESS] Repository successfully published to GitHub!
    echo  URL: https://github.com/DIVINE039/sih26146-vigil-chain
    echo ==========================================================
) else (
    echo.
    echo [!] Push failed.
    echo Ensure that:
    echo  1. You have created an empty repo named 'sih26146-vigil-chain' at https://github.com/new
    echo  2. You did NOT check 'Add a README file' while creating it.
)
echo.
pause
