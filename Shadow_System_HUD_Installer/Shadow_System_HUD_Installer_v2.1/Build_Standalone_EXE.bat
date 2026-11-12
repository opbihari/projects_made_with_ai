@echo off
title Shadow System HUD - Standalone EXE Builder
color 0C
echo ======================================================================
echo       S H A D O W   S Y S T E M   H U D   -   E X E   B U I L D E R   
echo ======================================================================
echo.
cd /d "%~dp0"
echo [1/3] Ensuring Pillow, OpenCV, and PyInstaller are installed...
python -m pip install --upgrade pillow opencv-python pyinstaller
echo.
echo [2/3] Compiling standalone ShadowSystemHUD.exe and creating shortcuts...
python -u "%~dp0shadow_system_hud.py" --build-exe
echo.
echo [3/3] Done! You can now launch 'Shadow System HUD' from your Desktop or Start Menu.
pause
