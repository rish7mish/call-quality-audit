@echo off
setlocal
cd /d "%~dp0"
title VANI Quality - FINAL holdout score (run once)
set "PY="
python -c "print(1)" >nul 2>nul && set "PY=python"
if not defined PY ( py -3 -c "print(1)" >nul 2>nul && set "PY=py -3" )
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe""
if not defined PY ( echo Python not found. & pause & exit /b )
echo ============================================================
echo  FINAL SCORE: grades the 52 HOLDOUT calls with the frozen
echo  rules (v4). These calls were never used to tune the rules,
echo  so this is the honest agreement number. About $2.40.
echo ============================================================
set "LLM_PROVIDER=anthropic"
echo Paste your Anthropic API key (right-click to paste) and press Enter:
set /p LLM_API_KEY=Key: 
cls
echo.
echo [1/3] Grading the holdout calls (already-graded ones are skipped)...
%PY% grade_calls.py --split holdout
echo.
echo [2/3] FINAL agreement with the human auditors (holdout):
%PY% evaluate.py --split holdout
echo.
echo     ...and on all graded calls together (tune + holdout):
%PY% evaluate.py --split all
echo.
echo [3/3] Updating the top problems list with all graded calls...
%PY% root_causes.py
echo.
echo ============================================================
echo  DONE - you can close this window. Spend so far (estimate):
type usage_log.csv
echo  In the dashboard click "Reload data" - Agreement tab - holdout.
echo ============================================================
pause
