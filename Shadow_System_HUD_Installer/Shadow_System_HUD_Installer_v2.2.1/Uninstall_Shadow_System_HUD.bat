@echo off
title Shadow System HUD - Uninstaller
cd /d "%~dp0"
echo Uninstalling Shadow System HUD shortcuts and program files...
python -u "%~dp0shadow_system_hud.py" --uninstall
echo.
pause
