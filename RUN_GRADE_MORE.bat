@echo off
setlocal
cd /d "%~dp0"
title VANI Quality - grade more calls
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
set "N=20"
set /p N=How many NEW tune calls to grade? (Enter = 20, about $0.04 each): 
echo.
echo [1/3] Grading %N% new tune calls (calls already graded are skipped)...
%PY% grade_calls.py --split tune --limit %N%
echo.
echo [2/3] Agreement with the human auditors (all graded tune calls):
%PY% evaluate.py --split tune
echo.
echo [3/3] Updating the top problems list...
%PY% root_causes.py
echo.
echo ============================================================
echo  DONE - you can close this window now. Spend so far (estimate):
type usage_log.csv
echo  In the dashboard click "Reload data".
echo ============================================================
pause
