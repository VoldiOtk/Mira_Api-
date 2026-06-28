@echo off
color 0A
title MIRA - LANCEMENT COMPLET

cd /d "%~dp0"

echo.
echo  ============================================================
echo   MIRA - LANCEMENT COMPLET (Backend + Admin)
echo  ============================================================
echo.

:: Lancer le backend dans une nouvelle fenetre
echo  [1/2] Lancement du backend API...
start "MIRA Backend" /D "%~dp0" cmd /k start-backend.bat

:: Attendre que le backend soit pret
echo  [2/2] Attente demarrage backend (12 secondes)...
timeout /t 12 /nobreak > nul

:: Ouvrir les interfaces dans le navigateur
echo  Ouverture des interfaces...
start "" "http://127.0.0.1:8000"
timeout /t 1 /nobreak > nul
start "" "http://127.0.0.1:8000/admin"
timeout /t 1 /nobreak > nul
start "" "http://127.0.0.1:8000/docs"

echo.
echo  ============================================================
echo   SERVICES LANCES
echo   Backend API   : http://127.0.0.1:8000
echo   Docs Swagger  : http://127.0.0.1:8000/docs
echo   Admin         : http://127.0.0.1:8000/admin
echo   API interne   : http://127.0.0.1:8000/api/v1
echo   API publique  : http://127.0.0.1:8000/v1
echo  ============================================================
echo.
echo  NOTE : La partie client tourne separement (port 8001).
echo.
echo  Pour arreter Mira : fermez la fenetre "MIRA Backend"
echo.
pause
