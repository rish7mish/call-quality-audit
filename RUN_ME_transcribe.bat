@echo off
setlocal
cd /d "%~dp0"
title Step 1 - Turn call recordings into text
color 0F
echo.
echo ============================================================
echo   STEP 1: Turn the call recordings into text (Sarvam)
echo ============================================================
echo.

REM ---- 1. Check Python ----------------------------------------
python -c "print('ok')" >nul 2>nul
if errorlevel 1 (
    echo Python is not installed on this laptop. Installing it now...
    echo If Windows asks for permission, click YES.
    echo.
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    echo.
    echo ------------------------------------------------------------
    echo  Python install finished.
    echo  CLOSE this window and DOUBLE-CLICK RUN_ME_transcribe.bat AGAIN.
    echo  If it still says Python is missing, ask your team lead.
    echo ------------------------------------------------------------
    pause
    exit /b
)
echo [OK] Python found.

REM ---- 2. Install the Sarvam library --------------------------
echo Installing the Sarvam library (first time takes a minute)...
python -m pip install --quiet --disable-pip-version-check sarvamai
if errorlevel 1 (
    echo.
    echo [PROBLEM] Could not install the Sarvam library. Check the internet / Wi-Fi and try again.
    pause
    exit /b
)
echo [OK] Sarvam library ready.
echo.

REM ---- 3. Ask for the API key ---------------------------------
echo Paste the Sarvam API key below and press ENTER.
echo (To paste: RIGHT-CLICK inside this window.)
set /p SARVAM_API_KEY=Key:
if "%SARVAM_API_KEY%"=="" (
    echo No key entered. Close and start again.
    pause
    exit /b
)
echo.

REM ---- 4. Test on 3 calls -------------------------------------
echo ------------------------------------------------------------
echo  TEST RUN: 3 calls only. Takes 1-3 minutes...
echo ------------------------------------------------------------
python transcribe_sarvam.py --limit 3
echo.
if not exist "transcripts\text\*.txt" (
    echo [PROBLEM] The test did not produce any text files.
    echo Take a PHOTO of this window and send it to your team lead.
    pause
    exit /b
)
echo A folder will open now. Open ANY ONE .txt file inside it.
echo It should look like a conversation, for example:
echo     [00:03] S0: Namaste, main IndiaMART se bol rahi hoon
echo     [00:06] S1: haan boliye
start "" "transcripts\text"
echo.
echo If it looks like a conversation, come back here and press any key
echo to run ALL calls. If it looks wrong, just CLOSE this window
echo and send a screenshot of the .txt file to your team lead.
pause >nul

REM ---- 5. Full run --------------------------------------------
echo.
echo ------------------------------------------------------------
echo  FULL RUN: all calls. Takes about 15-30 minutes.
echo  Keep the laptop ON and connected to Wi-Fi. Do not close this window.
echo ------------------------------------------------------------
python transcribe_sarvam.py
echo.
echo ------------------------------------------------------------
echo  DONE. Take a PHOTO of the last few lines above and send to your team lead.
echo  If it says some FAILED, just double-click this file again -
echo  it only redoes the failed ones.
echo ------------------------------------------------------------
pause
