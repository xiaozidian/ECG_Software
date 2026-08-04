@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "VENV_PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%scripts\setup_windows.ps1"
  if errorlevel 1 (
    echo Windows 运行环境安装失败。
    pause
    exit /b 1
  )
)

cd /d "%PROJECT_ROOT%"
"%VENV_PYTHON%" app.py %*
if errorlevel 1 pause
