@echo off
echo ===================================================
echo   Gym Form Corrector - Automatic Startup Script
echo ===================================================
echo.

echo [1/2] Launching Backend Server (FastAPI + Socket.IO) in a new window...
start "Gym Form Corrector Backend" cmd /k ".\test_venv\Scripts\python -m backend.app.main"

echo [2/2] Launching Frontend Server (Vite + React) in this window...
cd web-frontend
npm run dev

pause
