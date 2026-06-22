@echo off
echo Iniciando BarberApp...
start "Flask API" cmd /k "python app.py"
timeout /t 2 /nobreak >nul
start "Astro Frontend" cmd /k "cd frontend && npm run dev"
echo.
echo Abriendo navegador en http://localhost:4321...
timeout /t 4 /nobreak >nul
start http://localhost:4321
