@echo off
rem Build dist\PromptShop.exe (single file, no console window).
rem Needs: pip install -r requirements.txt -r requirements-desktop.txt
cd /d "%~dp0"
rem Collect license texts of bundled software (shown in the Help tab).
python tools\collect_licenses.py
if errorlevel 1 (
  echo Collecting licenses failed.
  pause
  exit /b 1
)
python -m PyInstaller --noconfirm --clean --onefile --windowed --name PromptShop ^
  --add-data "app\static;app\static" ^
  --icon "assets\promptshop.ico" ^
  --collect-submodules uvicorn ^
  --exclude-module pytest ^
  promptshop_desktop.py
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)
echo.
echo Built: %~dp0dist\PromptShop.exe
