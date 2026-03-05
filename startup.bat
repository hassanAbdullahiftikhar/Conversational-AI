@echo off
rem Windows equivalent of startup.sh for convenience
set MODEL_TAG=qwen3.5:2b-q4_K_M

where nvidia-smi >nul 2>nul
if %errorlevel%==0 (
    echo GPU detected. Starting with GPU compose override...
    docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
) else (
    echo No GPU runtime detected. Starting standard compose stack...
    docker compose up -d --build
)

:: launch containers
@if errorlevel 1 (
    echo docker compose up failed with error %errorlevel%
    goto end
)
echo Waiting for Ollama to initialize...
rem pause for 20 seconds
timeout /t 20 /nobreak >nul
echo Pulling model inside ollama container...
docker compose exec ollama sh -lc "ollama rm qwen3.5:2b >/dev/null 2>&1 || true; ollama pull %MODEL_TAG%"
@if errorlevel 1 (
    echo model pull failed with error %errorlevel%
    goto end
)
echo System ready. Open http://localhost:3000

:end
echo.
echo Press any key to close this window...
	pause >nul
