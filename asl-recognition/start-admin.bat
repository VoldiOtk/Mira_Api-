@echo off
color 0B
title MIRA - ADMIN DASHBOARD

cd /d "%~dp0"

echo.
echo  ============================================================
echo   MIRA ADMIN DASHBOARD
echo  ============================================================
echo.

:: Verifier si le build admin existe
if exist "frontend\dashboardadmin\dist\index.html" (
    echo  [OK] Build admin present dans frontend\dashboardadmin\dist\
    echo.
    echo  L'admin est servi par le backend FastAPI.
    echo  Assurez-vous que le backend tourne (start-backend.bat).
    echo.
    echo  URL ADMIN : http://127.0.0.1:8000/admin
    echo.
    :: Verifier si le backend est actif
    netstat -an 2>nul | find "8000" | find "LISTENING" > nul 2>&1
    if errorlevel 1 (
        echo  [ATTENTION] Le port 8000 ne semble pas actif.
        echo  Lancez start-backend.bat d'abord, puis revenez ici.
        echo.
        set /p LAUNCH="Lancer le backend maintenant ? (o/n) : "
        if /i "%LAUNCH%"=="o" (
            start "MIRA Backend" /D "%~dp0" cmd /k start-backend.bat
            echo  [INFO] Attente demarrage backend (10s)...
            timeout /t 10 /nobreak > nul
        )
    ) else (
        echo  [OK] Backend actif sur le port 8000
    )
    echo.
    echo  Ouverture du dashboard admin...
    start "" "http://127.0.0.1:8000/admin"
) else (
    echo  [ATTENTION] Build admin absent (frontend\dashboardadmin\dist\index.html manquant)
    echo.
    echo  Pour construire le dashboard admin :
    echo    1. Allez dans frontend\dashboardadmin\
    echo    2. Lancez : npm install
    echo    3. Lancez : npm run build
    echo    4. Le build sera dans frontend\dashboardadmin\dist\
    echo.
    echo  En attendant, verifiez si Node.js est installe :
    node --version > nul 2>&1
    if errorlevel 1 (
        echo  [ERREUR] Node.js introuvable. Installez Node.js sur https://nodejs.org
    ) else (
        for /f "tokens=*" %%v in ('node --version 2^>^&1') do set NODE_VER=%%v
        echo  [OK] Node.js %NODE_VER% present
        echo.
        set /p BUILD="Lancer npm install + npm run build maintenant ? (o/n) : "
        if /i "%BUILD%"=="o" (
            cd frontend\dashboardadmin
            echo  [INFO] npm install...
            npm install
            echo  [INFO] npm run build...
            npm run build
            cd ..\..
            echo  [OK] Build termine - relancez start-admin.bat
        )
    )
)

echo.
pause
