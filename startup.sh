#!/bin/bash
set -e

MODEL_TAG="qwen3.5:2b-q4_K_M"

if command -v nvidia-smi >/dev/null 2>&1; then
	echo "GPU detected. Starting with GPU compose override..."
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
else
	echo "No GPU runtime detected. Starting standard compose stack..."
	docker compose up -d --build
fi

echo "Waiting for Ollama to initialize..."
sleep 20
docker compose exec ollama sh -lc "ollama rm qwen3.5:2b >/dev/null 2>&1 || true; ollama pull ${MODEL_TAG}"
echo "System ready. Open http://localhost:3000"
