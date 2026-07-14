@echo off
setlocal

pushd "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0init.ps1"
popd
exit /b %ERRORLEVEL%
