# 1. Project Overview
This project is a local e-commerce customer support chatbot designed for assignment-scale deployment. It uses two FastAPI microservices, a React frontend, and a local Ollama model runtime. The system is policy-driven and intentionally excludes RAG, tool-calling, and external API lookups.

# 2. Architecture
```text
[Frontend :3000]
      |
      | WebSocket /ws/chat/{session_id}, REST /api/*
      v
[API Gateway :8000]
      |
      | REST /internal/*
      v
[Conversation Manager :8001]
      |
      | REST /api/generate
      v
[Ollama :11434]
```

| Service | Port | Responsibility |
|---|---|---|
| frontend | 3000 | Browser UI, session controls, live token rendering |
| api-gateway | 8000 | Public REST and WebSocket entrypoint, orchestration of conv-manager + Ollama |
| conv-manager | 8001 | Session/history management, policy checks, prompt construction |
| ollama | 11434 | Local model inference runtime (`qwen3.5:2b-q4_K_M`) |

# 3. Prerequisites
- Docker Desktop for Windows
- Bash shell (Git Bash or WSL)
- Free ports: `3000`, `8000`, `8001`

# 4. Quick Start
1. Clone the repository.
2. Start the stack:

**Windows:**
```bat
startup.bat
```

**Linux / macOS:**
```bash
bash startup.sh
```
Both scripts detect GPU/CPU automatically, bring up all services, wait for Ollama to initialize, and pull the model inside the container.

3. Open `http://localhost:3000`.

# 5. Manual Setup (running without Docker)
```bash
# Terminal 1 - conv-manager
cd conv-manager
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8001
```

```bash
# Terminal 2 - api-gateway
cd api-gateway
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

```bash
# Terminal 3 - frontend
cd frontend
npm install
npm run dev
```

```bash
# Terminal 4 - ollama runtime
ollama pull qwen3.5:2b-q4_K_M
ollama run qwen3.5:2b-q4_K_M
```

# 6. Model Selection
`qwen3.5:2b-q4_K_M` is selected as the default runtime profile because it provides a better speed-memory-quality balance for local support chat. It is pulled directly from Ollama, requires no custom serving stack, and is significantly faster than heavier quantizations on CPU while preserving useful instruction quality.

# 7. Conversation Policies
Supported topics:
- Order status inquiries
- Return and refund policy questions
- Product availability questions
- Shipping time estimates
- Account FAQs (password reset and account deletion policy)

Refused topics:
- Pricing negotiation
- Legal complaints or threats
- Off-topic content (coding, politics, weather, and unrelated requests)

# 8. Performance Benchmarks
| Metric | Target | How to measure |
|---|---|---|
| TTFT (time-to-first-token) | ≤ 3.0 s average | `python stress_test.py` — TEST 1 `avg_ttft` |
| Full response time | ≤ 12.0 s average | `python stress_test.py` — TEST 1 `avg_total` |
| Concurrent sessions | 10 simultaneous WebSocket sessions | `python stress_test.py` — TEST 2 `success_count` |
| Over-capacity rejection | Extra connections gracefully rejected | `python stress_test.py` — TEST 3 `pass` |
| Session reset isolation | Post-reset responses are context-free | `python stress_test.py` — TEST 4 `pass` |

Run `python stress_test.py` against a live stack to populate results. Results are saved to `stress_test_results.json`.
For raw Ollama model latency (no gateway overhead) run `python benchmark.py`. Results are saved to `benchmark_results.json`.

# 9. API Reference
Public REST (gateway):
- `POST /api/sessions` -> `{ "session_id": "uuid" }`
- `DELETE /api/sessions/{session_id}` -> `{ "success": true }`
- `POST /api/sessions/{session_id}/reset` -> `{ "success": true }`
- `GET /health` -> `{ "status": "ok" }`

WebSocket:
- `GET /ws/chat/{session_id}`
- Client -> server:
```json
{ "type": "user_message", "content": "Where is my order?" }
```
- Server -> client token stream:
```json
{ "type": "token", "content": "partial text" }
```
- Server completion:
```json
{ "type": "done", "content": "" }
```
- Server error:
```json
{ "type": "error", "content": "reason" }
```

Internal REST (conv-manager):
- `POST /internal/build-prompt`
- `POST /internal/update-history`
- `POST /internal/reset-session`
- `POST /internal/create-session`
- `DELETE /internal/delete-session/{session_id}`

Ollama boundary:
- `POST /api/generate` with JSON prompt payload and stream mode.

# 10. Postman Collection
`postman_collection.json` is provided in the repository root. Import it in Postman using `Import -> File`, then run requests in order starting from `Create Session` to auto-populate `{{session_id}}`.

# 11. Known Limitations
- Session state is in-memory only and is lost on service restart.
- CPU-only inference can take roughly 5-20 seconds depending on host hardware and load.
- WebSocket sessions are authenticated via HMAC-SHA256 tokens. Tokens are single-use per session and are generated at `POST /api/sessions`; connections without a valid token are rejected with code 4401.
- Context window is constrained to the most recent 5 full rounds plus a compressed summary of up to 15 older rounds, with an estimated 1600-token hard budget for the full-context portion.

# 11.1 Performance Tuning Notes
- In this Docker setup, Ollama is typically CPU-only unless GPU passthrough is explicitly configured.
- `/api/generate` is bounded in the gateway. It is no longer unbounded because `num_predict` is explicitly sent on every request.
- Default inference controls (these match the values set in `docker-compose.yml`):
      - `OLLAMA_NUM_PREDICT` (default `256`)
      - `OLLAMA_NUM_CTX` (default `4096`)
      - `OLLAMA_TEMPERATURE` (default `0.65`)
      - `OLLAMA_TOP_P` (default `0.9`)
      - `OLLAMA_TOP_K` (default `40`)
      - `OLLAMA_REPEAT_PENALTY` (default `1.08`)
      - `OLLAMA_NUM_GPU` (default `-1`, offload as many layers as possible)
      - `OLLAMA_KEEP_ALIVE` (default `30m`)
- You can override these in `docker-compose.yml` under `api-gateway.environment`.
- Ollama is exposed on `localhost:11434` for local diagnostics and benchmark scripts.
- If responses still feel slow, reduce `OLLAMA_NUM_PREDICT` to `120-160` and restart compose.

# 11.2 Optional GPU Mode
- GPU mode is possible when Docker Desktop and drivers support device passthrough.
- Use:
```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```
- Verify in Ollama logs that compute is not CPU-only and layers are offloaded.

# 12. Project Structure
```text
repo-root/
|- conv-manager/
|  |- Dockerfile
|  |- requirements.txt
|  |- main.py
|  |- session_store.py
|  |- history_manager.py
|  |- memory_summarizer.py
|  |- prompt_builder.py
|  |- policy_enforcer.py
|- api-gateway/
|  |- Dockerfile
|  |- requirements.txt
|  |- main.py
|  |- llm_client.py
|  |- session_router.py
|  |- websocket_handler.py
|- frontend/
|  |- Dockerfile
|  |- nginx.conf
|  |- package.json
|  |- src/
|     |- App.jsx
|     |- App.css
|     |- hooks/useWebSocket.js
|     |- components/
|        |- WelcomeScreen.jsx
|        |- WelcomeScreen.css
|        |- MessageBubble.jsx
|        |- MessageBubble.css
|        |- ChatWindow.jsx
|        |- ChatWindow.css
|        |- SessionControls.jsx
|        |- SessionControls.css
|- docker-compose.yml
|- docker-compose.gpu.yml
|- startup.sh
|- startup.bat
|- benchmark.py
|- stress_test.py
|- postman_collection.json
|- README.md
```
