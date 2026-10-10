@echo off
setlocal
cd /d "%~dp0"
title VANI Quality - re-test an existing fix
set "PY="
python -c "print(1)" >nul 2>nul && set "PY=python"
if not defined PY ( py -3 -c "print(1)" >nul 2>nul && set "PY=py -3" )
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe""
if not defined PY ( echo Python not found. & pause & exit /b )
set "LLM_PROVIDER=anthropic"
echo Paste your Anthropic API key (right-click to paste) and press Enter:
set /p LLM_API_KEY=Key: 
cls
set "PID=P03"
set /p PID=Which fix to test? (Enter = P03): 
echo.
echo Same-moment test: 4 real failure moments x 3 tries x 2 versions (about $0.30-0.50)...
%PY% moment_test.py --only %PID% --cases 4 --tries 3
echo.
echo ============================================================
echo  DONE - Dashboard: page 9 "Reload data", then page 6.
echo ============================================================
pause
