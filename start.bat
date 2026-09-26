@echo off
rem restock-monitoring launcher: sets up what's missing, then starts the app.
setlocal
cd /d "%~dp0"

if not exist venv\Scripts\python.exe (
    echo Creating virtual environment...
    python -m venv venv || goto :error
)
venv\Scripts\python.exe -c "import fastapi, uvicorn, bs4, requests, curl_cffi" 2>nul || (
    echo Installing Python dependencies...
    venv\Scripts\python.exe -m pip install -r requirements.txt || goto :error
)

if not exist web\dist\index.html (
    echo Building the web UI...
    pushd web
    if not exist node_modules call npm install || goto :error
    call npm run build || goto :error
    popd
)

venv\Scripts\python.exe -m restock --open %*
goto :eof

:error
echo.
echo Setup failed - see the messages above.
pause
exit /b 1
