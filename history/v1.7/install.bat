@echo off
cd /d "%~dp0"
py -3.11-64 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Installation complete. Run start.bat.
pause
exit /b 0
:fail
echo Installation failed. Install Python 3.11 64-bit and retry.
pause
exit /b 1
