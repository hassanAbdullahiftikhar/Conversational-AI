#!/usr/bin/env bash
set -e


MAX_RETRIES=60
LLM_MAX_RETRIES=180
POLL_INTERVAL=10

# ── Parse optional flags ───────────────────────────────────────
BUILD_FLAG=""
if [ "${1}" = "--build" ]; then
    BUILD_FLAG="--build"
fi

# ── Detect GPU ─────────────────────────────────────────────────
if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
    echo "GPU detected. Starting with GPU compose override..."
    COMPOSE_FILES="-f docker-compose.yml -f docker-compose.gpu.yml"
else
    echo "No GPU runtime detected. Starting standard compose stack..."
    COMPOSE_FILES="-f docker-compose.yml"
fi

# ── Start all services ─────────────────────────────────────────
docker compose $COMPOSE_FILES up -d $BUILD_FLAG
if [ $? -ne 0 ]; then
    echo "ERROR: docker compose up failed."
    exit 1
fi

# ── Health poll: ASR service ───────────────────────────────────
echo "Waiting for asr-service to initialize (model download may take several minutes)..."
for i in $(seq 1 $MAX_RETRIES); do
    if curl -sf http://localhost:8002/health > /dev/null 2>&1; then
        echo "asr-service is healthy."
        break
    fi
    echo "  Waiting for asr-service... ($i/$MAX_RETRIES)"
    sleep $POLL_INTERVAL
done

# ── Health poll: TTS service ───────────────────────────────────
echo "Waiting for tts-service to initialize (model download may take several minutes)..."
for i in $(seq 1 $MAX_RETRIES); do
    if curl -sf http://localhost:8003/health > /dev/null 2>&1; then
        echo "tts-service is healthy."
        break
    fi
    echo "  Waiting for tts-service... ($i/$MAX_RETRIES)"
    sleep $POLL_INTERVAL
done

# ── Health poll: llm-engine ────────────────────────────────────
echo "Waiting for llm-engine to initialize (model download may take up to 10 minutes)..."
for i in $(seq 1 $LLM_MAX_RETRIES); do
    if curl -sf http://localhost:11434/health > /dev/null 2>&1; then
        echo "llm-engine is healthy."
        break
    fi
    dl_mb=$(docker exec conversational-ai-llm-engine-1 sh -lc "du -sm /root/.cache/huggingface/hub/models--unsloth--gemma-4-E4B-it-GGUF/blobs/*.downloadInProgress 2>/dev/null | awk '{sum+=\$1} END {print sum+0}'" 2>/dev/null || echo 0)
    dl_pct=$((dl_mb * 100 / 5000))
    if [ "$dl_pct" -gt 99 ]; then dl_pct=99; fi
    echo "  Waiting for llm-engine... ($i/$LLM_MAX_RETRIES)  download~${dl_mb}MB (${dl_pct}%)"
    sleep $POLL_INTERVAL
done

# ── Health poll: API gateway ───────────────────────────────────
echo "Waiting for api-gateway to initialize..."
for i in $(seq 1 $MAX_RETRIES); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "api-gateway is healthy."
        break
    fi
    echo "  Waiting for api-gateway... ($i/$MAX_RETRIES)"
    sleep $POLL_INTERVAL
done

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Smart Home Assistant ready at http://localhost:3000"
echo "═══════════════════════════════════════════════════"
