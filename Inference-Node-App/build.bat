@echo off
setlocal
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
py -m PyInstaller --noconfirm --clean --onefile --windowed --name ModulogicalInferenceNode --add-data "src\ui;ui" src\main.py
if errorlevel 1 exit /b 1
echo.
echo Build complete: dist\ModulogicalInferenceNode.exe
pause
