@echo off
setlocal
set "DESKTOP_PYTHON=%~dp0.venv-desktop\Scripts\python.exe"
if not exist "%DESKTOP_PYTHON%" (
    echo Desktop environment missing. See Desktop setup in README.md.
    exit /b 1
)
if not exist "%~dp0static\vendor\three.module.js" goto missing_three
if not exist "%~dp0static\vendor\three.core.js" goto missing_three
if not exist "%~dp0static\vendor\jsm\controls\OrbitControls.js" goto missing_three

"%DESKTOP_PYTHON%" -B "%~dp0desktop.py"
exit /b %ERRORLEVEL%

:missing_three
echo Local Three.js files missing. See Desktop setup in README.md.
exit /b 1
