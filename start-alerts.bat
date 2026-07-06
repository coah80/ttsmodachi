@echo off
docker compose --profile alerts up --build -d tts-worker alerts
if errorlevel 1 (
    echo.
    echo docker compose failed. if the error mentions npipe or the docker API,
    echo Docker Desktop is not running yet. start it, wait for the whale, retry.
    exit /b 1
)
echo.
echo alerts service is starting. setup page: http://127.0.0.1:18081/setup
