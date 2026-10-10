@echo off
setlocal
cd /d "%~dp0"
title VANI Quality Dashboard
set "PY="
python -c "print(1)" >nul 2>nul && set "PY=python"
if not defined PY ( py -3 -c "print(1)" >nul 2>nul && set "PY=py -3" )
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe""
if not defined PY (
    echo Python not found. Run RUN_ME_transcribe.bat once first - it installs Python.
    pause
    exit /b
)
echo Installing / checking libraries (first time takes a few minutes)...
%PY% -m pip install --quiet --disable-pip-version-check -r requirements.txt
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    mkdir "%USERPROFILE%\.streamlit" 2>nul
    ( echo [general]& echo email = "" ) > "%USERPROFILE%\.streamlit\credentials.toml"
)
echo.
echo ============================================================
echo  Dashboard starting - your browser will open at
echo      http://localhost:8501  (or 8502, 8503... if that one is busy - see the Local URL below)
echo  Keep this window open while you use it. Close it to stop.
echo ============================================================
%PY% -m streamlit run dashboard.py
pause
