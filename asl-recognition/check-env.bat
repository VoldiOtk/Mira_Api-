@echo off
color 0B
title MIRA - VERIFICATION ENVIRONNEMENT

cd /d "%~dp0"

echo.
echo  ============================================================
echo   MIRA - VERIFICATION ENVIRONNEMENT
echo  ============================================================
echo.

set OK=[OK]
set MISSING=[MISSING]
set ERR=[ERREUR]

:: Python
python --version > nul 2>&1
if errorlevel 1 (
    echo  %MISSING%  Python - non installe
) else (
    for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
    echo  %OK%  Python - %PY_VER%
)

:: Node.js
node --version > nul 2>&1
if errorlevel 1 (
    echo  %MISSING%  Node.js - non installe (optionnel, pour build admin)
) else (
    for /f "tokens=*" %%v in ('node --version 2^>^&1') do set NODE_VER=%%v
    echo  %OK%  Node.js - %NODE_VER%
)

:: npm
npm --version > nul 2>&1
if errorlevel 1 (
    echo  %MISSING%  npm - non installe (optionnel)
) else (
    for /f "tokens=*" %%v in ('npm --version 2^>^&1') do set NPM_VER=%%v
    echo  %OK%  npm - v%NPM_VER%
)

:: venv
if exist "venv\Scripts\activate.bat" (
    echo  %OK%  venv - present
) else (
    echo  %MISSING%  venv - absent (lancez install-backend.bat)
)

:: uvicorn via venv
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat > nul 2>&1
    python -m uvicorn --version > nul 2>&1
    if errorlevel 1 (
        echo  %MISSING%  uvicorn - non installe dans le venv
    ) else (
        for /f "tokens=*" %%v in ('python -m uvicorn --version 2^>^&1') do set UV_VER=%%v
        echo  %OK%  uvicorn - %UV_VER%
    )
    python -c "import fastapi" > nul 2>&1
    if errorlevel 1 (
        echo  %MISSING%  fastapi - non installe dans le venv
    ) else (
        echo  %OK%  fastapi - installe
    )
) else (
    echo  [SKIP]  uvicorn / fastapi - venv absent
    echo  [SKIP]  fastapi - venv absent
)

:: Port 8000
netstat -an 2>nul | find "8000" | find "LISTENING" > nul 2>&1
if errorlevel 1 (
    echo  %OK%  Port 8000 - libre
) else (
    echo  [INFO] Port 8000 - occupe (backend probablement en cours)
)

:: .env
if exist ".env" (
    echo  %OK%  .env - present
) else (
    echo  %MISSING%  .env - absent (copiez .env.example vers .env)
)

:: backend importable
if exist "venv\Scripts\activate.bat" (
    python -c "import backend.app" > nul 2>&1
    if errorlevel 1 (
        echo  %ERR%  backend.app - import echoue (verifiez les dependances)
    ) else (
        echo  %OK%  backend.app - importable
    )
) else (
    echo  [SKIP]  backend.app - venv absent
)

:: Admin build
if exist "frontend\dashboardadmin\dist\index.html" (
    echo  %OK%  Admin build - present
) else (
    echo  %MISSING%  Admin build - absent (npm run build dans frontend\dashboardadmin\)
)

:: Public router /v1
if exist "backend\routers\public_v1_router.py" (
    echo  %OK%  API publique /v1 - router present
) else (
    echo  %MISSING%  backend\routers\public_v1_router.py - absent
)

echo.
echo  ============================================================
echo   Verification terminee.
echo  ============================================================
echo.
pause
