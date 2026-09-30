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
    echo.
    echo [*] Updating the live console ^(docs folder -^> gh-pages branch^)...
    git subtree push --prefix docs origin gh-pages
    echo  Live: https://adityak39l.github.io/SIH_26146/
) else (
    echo.
    echo [!] Push failed. Check your internet connection or git credentials.
)
echo.
pause
