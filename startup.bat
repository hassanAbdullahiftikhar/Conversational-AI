@echo off
rem NexaKart startup script for Windows

set MAX_RETRIES=60
set LLM_MAX_RETRIES=180
set POLL_INTERVAL=10
set DO_BUILD=

rem ── Optional flag: rebuild images ────────────────────────────
rem Usage:
rem   startup.bat          -> fast start (no image rebuild)
rem   startup.bat --build  -> rebuild images (when Dockerfiles/requirements change)
rem   startup.bat --rebuild-corpus -> clone repos and rebuild RAG corpus
set REBUILD_CORPUS=
if /I "%~1"=="--rebuild-corpus" (
    set DO_BUILD=--build
    set REBUILD_CORPUS=1
)
if /I "%~1"=="--build" (
    set DO_BUILD=--build
)

rem ── Preflight: ensure Docker daemon is reachable ───────────
docker version >nul 2>nul
if errorlevel 1 (
    echo ERROR: Docker daemon is not reachable.
    echo.
    echo Start Docker Desktop, wait until it reports "Engine running", then retry:
    echo   startup.bat
    echo or
    echo   startup.bat --build
    goto end
)

rem ── Optional: Rebuild RAG corpus ─────────────────────────────
if defined REBUILD_CORPUS (
    echo.
    echo ==== Building RAG Corpus ======
    if not exist "conv-manager\smart_home_rag\repos" mkdir "conv-manager\smart_home_rag\repos"
    
    echo Cloning repos (this may take several minutes)...
    if not exist "conv-manager\smart_home_rag\repos\home-assistant.io" (
        git clone https://github.com/home-assistant/home-assistant.io.git conv-manager\smart_home_rag\repos\home-assistant.io
    ) else (
        echo   home-assistant.io already exists, skipping.
    )
    
    if not exist "conv-manager\smart_home_rag\repos\zigbee2mqtt.io" (
        git clone https://github.com/Koenkk/zigbee2mqtt.io.git conv-manager\smart_home_rag\repos\zigbee2mqtt.io
    ) else (
        echo   zigbee2mqtt.io already exists, skipping.
    )
    
    if not exist "conv-manager\smart_home_rag\repos\esphome-docs" (
        git clone https://github.com/esphome/esphome-docs.git conv-manager\smart_home_rag\repos\esphome-docs
    ) else (
        echo   esphome-docs already exists, skipping.
    )
    
    echo Building corpus chunks...
    python conv-manager\smart_home_rag\corpus_builder.py
    if errorlevel 1 (
        echo WARNING: corpus_builder.py failed. RAG may have limited data.
    ) else (
        echo Corpus built successfully.
    )
    echo ================================
    echo.
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
    goto poll_llm
)
curl -sf http://localhost:8003/health >nul 2>nul
if %errorlevel%==0 (
    echo tts-service is healthy.
    goto poll_llm
)
echo   Waiting for tts-service... (%counter%/%MAX_RETRIES%)
timeout /t %POLL_INTERVAL% /nobreak >nul
goto poll_tts

rem ── Health poll: llm-engine ──────────────────────────────────
echo Waiting for llm-engine to initialize (model download may take up to 10 minutes)...
set /a counter=0
:poll_llm
set /a counter+=1
if %counter% gtr %LLM_MAX_RETRIES% (
    echo WARNING: llm-engine did not become healthy within timeout.
    goto poll_gateway
)
curl -sf http://localhost:11434/health >nul 2>nul
if %errorlevel%==0 (
    echo llm-engine is healthy.
    goto poll_gateway
)
set DL_MB=0
for /f %%p in ('docker exec conversational-ai-llm-engine-1 sh -lc "du -sm /root/.cache/huggingface/hub/models--unsloth--gemma-4-E4B-it-GGUF/blobs/*.downloadInProgress 2>/dev/null | awk '{sum+=$1} END {print sum+0}'" 2^>nul') do set DL_MB=%%p
set /a DL_PCT=(DL_MB*100)/5000
if %DL_PCT% gtr 99 set DL_PCT=99
echo   Waiting for llm-engine... (%counter%/%LLM_MAX_RETRIES%)  download~%DL_MB%MB (%DL_PCT%%)
timeout /t %POLL_INTERVAL% /nobreak >nul
goto poll_llm

rem ── Health poll: API gateway ───────────────────────────────
echo Waiting for api-gateway to initialize...
set /a counter=0
:poll_gateway
set /a counter+=1
if %counter% gtr %MAX_RETRIES% (
    echo WARNING: api-gateway did not become healthy within timeout.
    goto ready_banner
)
curl -sf http://localhost:8000/health >nul 2>nul
if %errorlevel%==0 (
    echo api-gateway is healthy.
    goto ready_banner
)
echo   Waiting for api-gateway... (%counter%/%MAX_RETRIES%)
timeout /t %POLL_INTERVAL% /nobreak >nul
goto poll_gateway

:ready_banner
echo.
echo ===================================================
echo   Smart Home Assistant ready at http://localhost:3000
echo ===================================================
echo.
echo NOTE: If RAG search_docs returns no results, run:
echo   startup.bat --rebuild-corpus
echo.

:end
echo.
echo Press any key to close this window...
	pause >nul
