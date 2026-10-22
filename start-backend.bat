@echo off
setlocal
cd /d "%~dp0backend"
if errorlevel 1 goto failed

if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. Creating environment...
  py -3.13 -m venv .venv
  if errorlevel 1 goto failed
)

".venv\Scripts\python.exe" -c "import uvicorn, fastapi, multipart, pandas, openpyxl, xlrd, sqlalchemy, aiosqlite, pydantic_settings, httpx, pyarrow" >nul 2>&1
if errorlevel 1 (
  echo Installing backend dependencies...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto failed
)

echo Starting backend: http://127.0.0.1:8000
echo Keep this window open. Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo Backend startup failed. Please copy the error above to Codex.
pause
exit /b 1
