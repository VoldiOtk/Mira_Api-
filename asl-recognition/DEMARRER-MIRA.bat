@echo off
color 0A
title MIRA - BACKEND + ADMIN
cls

echo.
echo  ########################################################
echo  ##                                                    ##
echo  ##   M I R A  -  Backend + Admin                     ##
echo  ##   GV TECH  |  Reconnaissance Langue des Signes    ##
echo  ##                                                    ##
echo  ########################################################
echo.

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

:: ── [1/4] Verifier Python ──────────────────────────────────────────────────
echo  [1/4]  Verification Python...
python --version > nul 2>&1
if errorlevel 1 (
    color 0C
    echo  [ERREUR] Python introuvable.
    echo  Installez Python 3.8+ depuis https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo         OK - %PY_VER%

:: ── [2/4] Verifier venv ────────────────────────────────────────────────────
echo  [2/4]  Verification venv...
if not exist "%ROOT%\venv\Scripts\activate.bat" (
    echo         Venv absent - creation en cours...
    python -m venv "%ROOT%\venv"
    if errorlevel 1 (
        color 0C
        echo  [ERREUR] Impossible de creer le venv.
        pause
        exit /b 1
    )
    call "%ROOT%\venv\Scripts\activate.bat"
    pip install -r "%ROOT%\requirements.txt" -q --no-warn-script-location
    echo         OK - venv cree et dependances installees
) else (
    echo         OK - venv present
)

:: ── [3/4] Verifier .env ────────────────────────────────────────────────────
echo  [3/4]  Verification configuration...
if not exist "%ROOT%\.env" (
    if exist "%ROOT%\.env.example" (
        copy "%ROOT%\.env.example" "%ROOT%\.env" > nul
        echo         .env cree depuis .env.example
        echo         [!] Editez .env et renseignez MIRA_ADMIN_PASSWORD
    ) else (
        echo  [ATTENTION] .env et .env.example absents
    )
) else (
    echo         OK - .env present
)

:: ── [4/4] Verifier fastapi + uvicorn ────────────────────────────────────────
echo  [4/4]  Verification dependances...
call "%ROOT%\venv\Scripts\activate.bat" > nul 2>&1
python -c "import fastapi, uvicorn" > nul 2>&1
if errorlevel 1 (
    echo         Installation des dependances...
    pip install -r "%ROOT%\requirements.txt" -q --no-warn-script-location
)
python -c "import fastapi, uvicorn" > nul 2>&1
if errorlevel 1 (
    color 0C
    echo  [ERREUR] fastapi ou uvicorn toujours manquant.
    echo  Lancez install-backend.bat puis reessayez.
    pause
    exit /b 1
)
echo         OK - fastapi + uvicorn prets

echo.
echo  ########################################################
echo  ##   Demarrage du backend sur le port 8000...        ##
echo  ########################################################
echo.

:: Lancer le backend dans une nouvelle fenetre
start "MIRA :: Backend API :8000" /D "%ROOT%" cmd /k venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload

:: Attendre que le backend soit operationnel
echo  Attente demarrage backend (10 secondes)...
timeout /t 10 /nobreak > nul

:: Verifier que le port est bien ecoute
netstat -an 2>nul | find "8000" | find "LISTENING" > nul 2>&1
if errorlevel 1 (
    color 0E
    echo  [ATTENTION] Le port 8000 ne repond pas encore.
    echo  Attendez quelques secondes et verifiez la fenetre backend.
    color 0A
)

:: Ouvrir le dashboard admin et la doc
echo  Ouverture du dashboard admin et de la documentation...
start "" "http://127.0.0.1:8000/admin"
timeout /t 1 /nobreak > nul
start "" "http://127.0.0.1:8000/docs"

echo.
echo  ########################################################
echo  ##                                                    ##
echo  ##        *** MIRA BACKEND EST EN LIGNE ***           ##
echo  ##                                                    ##
echo  ########################################################
echo.
echo  SERVICES ACTIFS :
echo  ──────────────────────────────────────────────────────
echo   Backend API      : http://127.0.0.1:8000
echo   Documentation    : http://127.0.0.1:8000/docs
echo   Admin Dashboard  : http://127.0.0.1:8000/admin
echo   API interne      : http://127.0.0.1:8000/api/v1
echo   API publique     : http://127.0.0.1:8000/v1
echo  ──────────────────────────────────────────────────────
echo.
echo  ARCHITECTURE SEPAREE :
echo   Client Django    : http://127.0.0.1:8001  (lancer depuis le dossier client)
echo  ──────────────────────────────────────────────────────
echo.
echo  Pour arreter : fermez la fenetre "MIRA :: Backend API :8000"
echo.
echo  [ Cette fenetre peut etre fermee ]
echo.
pause
