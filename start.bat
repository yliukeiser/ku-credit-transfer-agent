@echo off
cd /d "%~dp0"
echo ============================================
echo  Keiser University Credit Transfer Agent
echo ============================================
echo.
echo Running from: %CD%
echo.

REM Check if API key is already set
if "%ANTHROPIC_API_KEY%"=="" (
    echo Enter your Anthropic API key below.
    echo Get it from: https://console.anthropic.com
    echo.
    set /p ANTHROPIC_API_KEY="Paste API key here and press Enter: "
    echo.
)

echo Starting server...
echo.
echo Once you see "Running on http://127.0.0.1:5000"
echo open your browser and go to: http://localhost:5000
echo.
echo Press Ctrl+C to stop the server.
echo.

python app.py

pause
