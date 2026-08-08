@echo off
REM Benchmark Dashboard Startup Script
REM Starts FastAPI backend and opens dashboard in browser

echo.
echo ====================================================
echo     Benchmark Dashboard - Starting...
echo ====================================================
echo.

REM Change to project directory
cd /d "E:\projects\ollama-bench"

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Please install Python 3.10 or later.
    echo Visit: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Check if FastAPI is installed
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo [WARNING] FastAPI not installed. Installing dependencies...
    pip install fastapi uvicorn websockets
)

REM Check if Ollama is running
echo Checking Ollama server...
timeout /t 1 /nobreak >nul
python -c "import requests; requests.get('http://localhost:11434/api/tags', timeout=2)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [WARNING] Ollama is not running!
    echo Please start Ollama with: ollama serve
    echo.
    pause
)

REM Start the dashboard in a new window
echo Starting FastAPI server...
start "Benchmark Dashboard" python dashboard.py

REM Wait for server to start
echo Waiting for server to start...
timeout /t 3 /nobreak >nul

REM Open browser to dashboard
echo Opening dashboard in browser...
timeout /t 1 /nobreak >nul
start http://localhost:8000

echo.
echo ====================================================
echo Dashboard is running!
echo - Server: http://localhost:8000
echo - Close the command window to stop the dashboard
echo ====================================================
echo.

pause
