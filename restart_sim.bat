@echo off
rem Rebuild and recreate the sim containers: picks up .env, docker-compose.yml and frontend changes,
rem and restarts the cognition / bg_llm workers on the current backend code.
cd /d "%~dp0"
docker compose up -d --build
echo.
echo Done. This window closes in 20 seconds.
timeout /t 20
