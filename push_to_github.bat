@echo off
echo ==========================================================
echo  Pushing SIH_26146 to GitHub
echo  Account: adityak39l
echo  Repo: https://github.com/adityak39l/SIH_26146
echo ==========================================================
echo.

git branch -M main
echo [*] Pushing changes to GitHub...
git push -u origin main

if %errorlevel% equ 0 (
    echo.
    echo ==========================================================
    echo  [SUCCESS] Code successfully pushed to GitHub!
    echo  URL: https://github.com/adityak39l/SIH_26146
    echo ==========================================================
) else (
    echo.
    echo [!] Push failed. Check your internet connection or git credentials.
)
echo.
pause
