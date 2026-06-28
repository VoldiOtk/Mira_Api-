@echo off
color 0A
title MIRA - INSTALLATION BACKEND

cd /d "%~dp0"

echo.
echo  ============================================================
echo   MIRA - INSTALLATION DES DEPENDANCES BACKEND
echo  ============================================================
echo.

:: Verifier Python
python --version > nul 2>&1
if errorlevel 1 (
    color 0C
    echo  [ERREUR] Python introuvable. Installez Python 3.8+ et relancez.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PYTHON_VER=%%v
echo  [OK] %PYTHON_VER% detecte

:: Creer le venv si absent
if not exist "venv\Scripts\activate.bat" (
    echo  [INFO] Creation du venv...
    python -m venv venv
    if errorlevel 1 (
        color 0C
        echo  [ERREUR] Echec creation venv.
        pause
        exit /b 1
    )
    echo  [OK] venv cree
) else (
    echo  [OK] venv deja present
)

:: Activer le venv
call venv\Scripts\activate.bat
echo  [OK] venv active

:: Mettre a jour pip
echo  [INFO] Mise a jour pip...
python -m pip install --upgrade pip

:: Installer les dependances
if exist "requirements.txt" (
    echo  [INFO] Installation des dependances depuis requirements.txt...
    pip install -r requirements.txt
    echo.
    echo  [OK] Dependances installees
) else (
    echo  [ATTENTION] requirements.txt absent - rien a installer
)

:: Confirmer uvicorn et fastapi
python -c "import fastapi, uvicorn" > nul 2>&1
if errorlevel 1 (
    color 0E
    echo  [ATTENTION] fastapi ou uvicorn toujours manquant apres installation.
    echo  Verifiez requirements.txt et la connexion internet.
) else (
    echo  [OK] fastapi + uvicorn operationnels
)

:: Creer .env si absent
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" > nul
        echo  [OK] .env cree depuis .env.example
        echo  [INFO] Editez .env pour configurer GEMINI_API_KEY et MIRA_ADMIN_PASSWORD
    )
)

echo.
echo  ============================================================
echo   Installation terminee. Lancez start-backend.bat
echo  ============================================================
echo.
pause
