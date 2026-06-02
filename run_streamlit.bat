@echo off
cd /d "%~dp0"
title Data Warehouse Builder - Streamlit

if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat

echo.
echo ============================================================
echo  Data Warehouse Builder - Streamlit
echo ============================================================
echo  Server:  http://127.0.0.1:8501
echo  KEEP THIS WINDOW OPEN. Press Ctrl+C to stop.
echo  (Browser opens separately — avoids Windows crash)
echo ============================================================
echo.

REM Open browser after server starts (separate process — safe on Windows)
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8501"

python -m streamlit run streamlit_app.py ^
  --server.port 8501 ^
  --server.address 127.0.0.1 ^
  --server.headless true ^
  --server.fileWatcherType none

echo.
echo Streamlit stopped (exit code %ERRORLEVEL%).
if %ERRORLEVEL% NEQ 0 (
  echo.
  echo Windows crash code -1073741819 = native crash. Try:
  echo   1. Run this .bat as Administrator
  echo   2. Temporarily disable antivirus
  echo   3. pip install --force-reinstall streamlit==1.45.1
  echo   4. Open http://127.0.0.1:8501 manually in Chrome/Edge
)
pause
