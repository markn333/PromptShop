@echo off
rem Start PromptShop and open it in the browser. Stop with Ctrl+C.
cd /d "%~dp0"
python -m app %*
if errorlevel 1 pause
