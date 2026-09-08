@echo off
setlocal
set "PS_EXE=powershell.exe"
where pwsh.exe >nul 2>&1
if not errorlevel 1 set "PS_EXE=pwsh.exe"
if "%PS_EXE%"=="powershell.exe" if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" set "PS_EXE=%ProgramFiles%\PowerShell\7\pwsh.exe"
"%PS_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\clean_fixture_data.ps1" %*
set "LAUNCH_EXIT=%ERRORLEVEL%"
if not "%LAUNCH_EXIT%"=="0" pause
exit /b %LAUNCH_EXIT%
