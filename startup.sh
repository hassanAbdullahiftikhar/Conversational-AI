#!/usr/bin/env bash
set -e

MODEL_TAG="qwen3.5:2b-q4_K_M"
MAX_RETRIES=30
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

# ── Health poll: Ollama ────────────────────────────────────────
echo "Waiting for Ollama to initialize..."
for i in $(seq 1 $MAX_RETRIES); do
    if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "Ollama is healthy."
        break
    fi
    echo "  Waiting for Ollama... ($i/$MAX_RETRIES)"
    sleep $POLL_INTERVAL
done

# ── Pull LLM model ────────────────────────────────────────────
echo "Pulling model inside ollama container..."
docker compose exec ollama sh -lc "ollama list | grep -q \"$MODEL_TAG\" || ollama pull \"$MODEL_TAG\""
if [ $? -ne 0 ]; then
    echo "WARNING: model pull failed."
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  NexaKart ready at http://localhost:3000"
echo "═══════════════════════════════════════════════════"
