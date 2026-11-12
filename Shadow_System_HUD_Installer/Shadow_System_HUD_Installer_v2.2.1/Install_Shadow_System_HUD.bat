@echo off
title Shadow System HUD - Windows 11 Installer
color 0C
echo ======================================================================
echo             S H A D O W   S Y S T E M   H U D   S E T U P             
echo ======================================================================
echo.
cd /d "%~dp0"
if not exist "%~dp0shadow_system_hud.py" (
    echo [ERROR] shadow_system_hud.py was not found next to this batch file!
    echo Please right-click the ZIP file and click 'Extract All...' before running this installer.
    pause
    exit /b 1
)
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found on your PATH.
    echo Please install Python 3.8+ from https://www.python.org/ and tick 'Add Python to PATH'.
    pause
    exit /b 1
)
echo [1/2] Checking required dependency (Pillow)...
python -c "import PIL" >nul 2>nul
if %errorlevel% neq 0 (
    echo Installing Pillow...
    python -m pip install --upgrade pillow
)
echo [2/2] Installing Shadow System HUD and creating shortcuts...
echo.
python -u "%~dp0shadow_system_hud.py" --install
echo.
echo ======================================================================
echo   SUCCESS! Shadow System HUD is now installed and launching on screen.
echo ======================================================================
timeout /t 4
exit /b 0
