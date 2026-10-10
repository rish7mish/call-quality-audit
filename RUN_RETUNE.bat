@echo off
setlocal
cd /d "%~dp0"
title VANI Quality - re-grade with the latest rules
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
echo.
REM keep the old fix/test results aside - they were made with the old rules
if exist "fixes" if not exist "fixes_v1" ren fixes fixes_v1
if exist "tests" if not exist "tests_v1" ren tests tests_v1
echo [1/3] Re-grading ALL already-graded tune calls with the new rules (about $0.04 per call)...
%PY% grade_calls.py --split tune --regrade
echo.
echo [2/3] Agreement with the human auditors:
%PY% evaluate.py --split tune
echo.
echo ------------------------------------------------------------
echo  Look at the agreement above. Grade 20 MORE tune calls now?
echo  (about $1.00)   Y = yes,  N = stop here
echo ------------------------------------------------------------
choice /c YN /n /m "Your choice [Y/N]: "
if errorlevel 2 goto :problems
%PY% grade_calls.py --split tune --limit 20
%PY% evaluate.py --split tune
:problems
echo.
echo [3/3] Updating the top problems list (a few cents)...
%PY% root_causes.py
echo.
echo ============================================================
echo  DONE. Spend so far (estimate):
type usage_log.csv
echo.
echo  In the dashboard click "Reload data". Fixes/tests are not re-run here
echo  (they are the expensive part) - we'll run them once the rules are good.
echo ============================================================
pause
