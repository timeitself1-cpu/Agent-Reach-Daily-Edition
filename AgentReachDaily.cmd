@echo off
rem Agent Reach Daily launcher: starts the window with this folder's own Python environment (.venv).
rem The console closes immediately; the app itself runs without one (pythonw.exe).
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%.venv\Scripts\pythonw.exe" (
  echo Agent Reach Daily is not set up yet. Open PowerShell in this folder and run:
  echo.
  echo   powershell -ExecutionPolicy Bypass -File .\Setup-AgentReachDaily.ps1
  echo.
  pause
  exit /b 1
)
start "Agent Reach Daily" /D "%ROOT%." "%ROOT%.venv\Scripts\pythonw.exe" -m agent_reach.daily --gui %*
endlocal
