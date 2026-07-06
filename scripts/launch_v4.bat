@echo off
echo ========================================================
echo Wickham Roofing AI Pipeline (V4 Truck Server) Launcher
echo ========================================================
echo.

echo [1] Initializing data directories...
if not exist "data\backups" (
    mkdir "data\backups"
    echo   - Created data\backups directory.
) else (
    echo   - data\backups directory verified.
)
echo.

echo [2] Activating Python Virtual Environment...
call .\venv\Scripts\activate
if %errorlevel% neq 0 (
    echo [ERROR] Failed to activate virtual environment. Have you run 'python -m venv venv' and installed requirements?
    pause
    exit /b %errorlevel%
)
echo   - Virtual environment activated.
echo.

echo [3] Checking Environment Configurations...
echo   - SQLite Database Path: data\truck_server.db
echo   - Redis Connection: redis://localhost:6379
echo.

echo [4] Starting Uvicorn FastAPI Server...
echo ========================================================
echo NOTE: Open a NEW terminal to start your Ngrok tunnel!
echo Command: ngrok http 8000
echo ========================================================
echo.
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
