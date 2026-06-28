@echo off
color 0A
title MIRA - BACKEND API
cd /d "%~dp0"
echo.
echo  ============================================================
echo   MIRA BACKEND - FastAPI sur http://127.0.0.1:8000
echo  ============================================================
echo.

:: Chercher Python 3.11 installe proprement
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if "%PY%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if "%PY%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if "%PY%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if "%PY%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python39\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
if "%PY%"=="" if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if "%PY%"=="" if exist "C:\Python311\python.exe" set "PY=C:\Python311\python.exe"
if "%PY%"=="" if exist "C:\Python310\python.exe" set "PY=C:\Python310\python.exe"
if "%PY%"=="" (
    color 0C
    echo  [ERREUR] Python 3.10+ introuvable.
    echo  Installez Python depuis https://www.python.org/downloads/
    echo  Cochez "Add Python to PATH" puis relancez.
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)
echo  [OK] Python trouve : %PY%

:: Detecter si le venv existant est un venv Windows Store (pyvenv.cfg)
if exist "venv\pyvenv.cfg" (
    findstr /i "WindowsApps" "venv\pyvenv.cfg" > nul 2>&1
    if not errorlevel 1 (
        echo  [INFO] Venv Windows Store detecte - suppression et recreation...
        "%PY%" -c "import shutil; shutil.rmtree(chr(118)+chr(101)+chr(110)+chr(118), ignore_errors=True)"
        echo  [OK] Ancien venv supprime
    )
)

:: Creer le venv avec le bon Python si absent
if not exist "venv\Scripts\activate.bat" (
    echo  [INFO] Creation du venv...
    "%PY%" -m venv venv
    if errorlevel 1 (
        color 0C
        echo  [ERREUR] Impossible de creer le venv.
        pause
        exit /b 1
    )
    echo  [OK] venv cree
) else (
    echo  [OK] venv present
)

call venv\Scripts\activate.bat
echo  [OK] venv active

:: Installer les dependances
if exist "requirements.txt" (
    echo  [INFO] Installation des dependances...
    venv\Scripts\python.exe -m pip install -r requirements.txt -q --no-warn-script-location
    if errorlevel 1 (
        color 0C
        echo  [ERREUR] pip install a echoue.
        pause
        exit /b 1
    )
    echo  [OK] Dependances installees
) else (
    echo  [ATTENTION] requirements.txt introuvable
)

:: Verifier fastapi + uvicorn
venv\Scripts\python.exe -c "import fastapi, uvicorn" > nul 2>&1
if errorlevel 1 (
    color 0C
    echo  [ERREUR] fastapi ou uvicorn manquant.
    pause
    exit /b 1
)
echo  [OK] fastapi + uvicorn OK

if not exist ".env" if exist ".env.example" copy ".env.example" ".env" > nul

echo.
echo  ============================================================
echo   Demarrage...
echo   URL      : http://127.0.0.1:8000
echo   DOCS     : http://127.0.0.1:8000/docs
echo   ADMIN    : http://127.0.0.1:8000/admin
echo   API v1   : http://127.0.0.1:8000/api/v1/health
echo   API pub  : http://127.0.0.1:8000/v1/models
echo  ============================================================
echo.

venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload

echo.
echo  [INFO] Serveur arrete.
pause