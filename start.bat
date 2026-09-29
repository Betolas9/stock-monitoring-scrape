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

rem Rebuild the web UI whenever its source changed (e.g. after a git pull):
rem exit code 2 = npm install needed, 1 = build needed, 0 = up to date
venv\Scripts\python.exe -m restock.webbuild
set UI_STATE=%errorlevel%
if %UI_STATE%==2 (
    echo Installing web UI packages...
    pushd web
    call npm install || goto :error
    popd
    venv\Scripts\python.exe -m restock.webbuild --mark-installed
    set UI_STATE=1
)
if %UI_STATE%==1 (
    echo Building the web UI...
    pushd web
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
