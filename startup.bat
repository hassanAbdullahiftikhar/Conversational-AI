@echo off
rem NexaKart startup script for Windows
set MODEL_TAG=qwen3.5:2b-q4_K_M
set MAX_RETRIES=30
set POLL_INTERVAL=10
set DO_BUILD=

rem ── Optional flag: rebuild images ────────────────────────────
rem Usage:
rem   startup.bat          -> fast start (no image rebuild)
rem   startup.bat --build  -> rebuild images (when Dockerfiles/requirements change)
if /I "%~1"=="--build" (
    set DO_BUILD=--build
)

rem ── Detect GPU ─────────────────────────────────────────────
where nvidia-smi >nul 2>nul
if %errorlevel%==0 (
    echo GPU detected. Starting with GPU compose override...
    rem Bring down any stale containers first to avoid Docker network/DNS issues
    docker compose -f docker-compose.yml -f docker-compose.gpu.yml down
    docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d %DO_BUILD%
) else (
    echo No GPU runtime detected. Starting standard compose stack...
    docker compose down
    docker compose up -d %DO_BUILD%
)

@if errorlevel 1 (
    echo ERROR: docker compose up failed with error %errorlevel%
    goto end
)

rem ── Health poll: ASR service ───────────────────────────────
echo Waiting for asr-service to initialize (model download may take several minutes)...
set /a counter=0
:poll_asr
set /a counter+=1
if %counter% gtr %MAX_RETRIES% (
    echo WARNING: asr-service did not become healthy within timeout.
    goto poll_tts_start
)
curl -sf http://localhost:8002/health >nul 2>nul
if %errorlevel%==0 (
    echo asr-service is healthy.
    goto poll_tts_start
)
echo   Waiting for asr-service... (%counter%/%MAX_RETRIES%)
timeout /t %POLL_INTERVAL% /nobreak >nul
goto poll_asr

rem ── Health poll: TTS service ───────────────────────────────
:poll_tts_start
echo Waiting for tts-service to initialize (model download may take several minutes)...
set /a counter=0
:poll_tts
set /a counter+=1
if %counter% gtr %MAX_RETRIES% (
    echo WARNING: tts-service did not become healthy within timeout.
    goto poll_ollama_start
)
curl -sf http://localhost:8003/health >nul 2>nul
if %errorlevel%==0 (
    echo tts-service is healthy.
    goto poll_ollama_start
)
echo   Waiting for tts-service... (%counter%/%MAX_RETRIES%)
timeout /t %POLL_INTERVAL% /nobreak >nul
goto poll_tts

rem ── Health poll: Ollama ────────────────────────────────────
:poll_ollama_start
echo Waiting for Ollama to initialize...
set /a counter=0
:poll_ollama
set /a counter+=1
if %counter% gtr %MAX_RETRIES% (
    echo WARNING: Ollama did not become healthy within timeout.
    goto pull_model
)
curl -sf http://localhost:11434/api/tags >nul 2>nul
if %errorlevel%==0 (
    echo Ollama is healthy.
    goto pull_model
)
echo   Waiting for Ollama... (%counter%/%MAX_RETRIES%)
timeout /t %POLL_INTERVAL% /nobreak >nul
goto poll_ollama

rem ── Pull LLM model ────────────────────────────────────────
:pull_model
echo Pulling model inside ollama container...
docker compose exec ollama sh -lc "ollama list | grep -q %MODEL_TAG% || ollama pull %MODEL_TAG%"
@if errorlevel 1 (
    echo WARNING: model pull failed with error %errorlevel%
)

echo.
echo ===================================================
echo   NexaKart ready at http://localhost:3000
echo ===================================================

:end
echo.
echo Press any key to close this window...
	pause >nul
