# Smart Home Ecosystem Support Assistant

# 1. Project Overview
This project is a local conversational assistant stack using FastAPI microservices, a React frontend, local llama.cpp runtime, and local voice services for streaming ASR and TTS. The current Phase 7 path removes Ollama, uses llama.cpp for both chat and embeddings, and includes a bounded smart-home RAG corpus with native `/v1/embeddings`.

# 2. Architecture
```text
[Frontend :3000]
      |
      | WebSocket /ws/chat/{session_id}, REST /api/*
      v
[API Gateway :8000]
      |\
      | \ REST /internal/*
      |  \
      |   -> [Conversation Manager :8001]
      |
      |-> WebSocket /ws/transcribe
      |    -> [ASR Service :8002]
      |
      |-> REST /synthesize
      |    -> [TTS Service :8003]
      |
      -> REST /v1/chat/completions
           -> [LLM Engine :11434] (llama.cpp with gemma-4-E4B-it + embeddings)
```

| Service | Port | Responsibility |
|---|---|---|
| frontend | 3000 | Browser UI, session controls, live token rendering |
| api-gateway | 8000 | Public REST and WebSocket entrypoint, orchestration of conv-manager + llama.cpp, tool-call interception |
| conv-manager | 8001 | Session/history management, policy checks, prompt construction, typed tool-router execution |
| asr-service | 8002 | Streaming Moonshine ASR over WebSocket for PCM microphone input |
| tts-service | 8003 | Kokoro ONNX speech synthesis returning WAV audio |
| llm-engine | 11434 | Local model inference (llama.cpp with gemma-4-E4B-it) AND embedding generation via `/v1/embeddings` |

# 3. Prerequisites
- Docker Desktop for Windows
- Bash shell (Git Bash or WSL)
- Free ports: `3000`, `8000`, `8002`, `8003`, `11434`

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
Both scripts detect GPU/CPU automatically, bring up all services, wait for ASR, TTS, and llama.cpp to initialize, and ensure the configured model is available.

3. Open `http://localhost:3000`.
4. Allow microphone access in the browser if you want to test the voice path.

> **Note:** The first run will download the GGUF model (~5GB) and initialize services. This may take 10-15 minutes on first start.
>
> If `search_docs` returns no results, run: `startup.bat --rebuild-corpus` to clone documentation repos and build the RAG corpus.

## 4.1 Startup Troubleshooting (Windows)
If startup fails with an error similar to:

`open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`

then Docker Desktop is installed but the Docker engine is not running.

Use this sequence:
1. Launch Docker Desktop and wait until the status shows the engine is running.
2. Verify daemon reachability:
```powershell
docker version
```
3. Start the stack:
```powershell
startup.bat
```
4. Confirm service ports are listening:
```powershell
Test-NetConnection localhost -Port 8000
Test-NetConnection localhost -Port 8002
Test-NetConnection localhost -Port 8003
```
5. Run Phase 7 QA bundle:
```powershell
c:/Users/madha/source/repos/NLPA/NLPA2/Conversational-AI/.venv/Scripts/python.exe stress_test.py
c:/Users/madha/source/repos/NLPA/NLPA2/Conversational-AI/.venv/Scripts/python.exe voice_integration_test.py
c:/Users/madha/source/repos/NLPA/NLPA2/Conversational-AI/.venv/Scripts/python.exe conv-manager/smart_home_rag/retrieval_eval.py --embedding-mode hash
```

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
# Terminal 3 - asr-service
cd asr-service
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8002
```

```bash
# Terminal 4 - tts-service
cd tts-service
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8003
```

```bash
# Terminal 3 - frontend
cd frontend
npm install
npm run dev
```

```bash
# Terminal 5 - llm-engine (llama.cpp)
# Provides both /v1/chat/completions AND /v1/embeddings endpoints
# Requires downloading the GGUF model and running llama-server
llama-server --hf-repo unsloth/gemma-4-E4B-it-GGUF --hf-file gemma-4-E4B-it-Q4_K_M.gguf --port 11434
```

# 6. Model Selection
`gemma-4-E4B-it` is configured as the default runtime profile in the `llm-engine` (llama.cpp).

If you see model load errors, ensure that your `llama.cpp` container image supports the `gemma4` architecture.

# 6.1 Smart-Home Capabilities (Phase 7 + Phase 8)
- Curated smart-home corpus pipeline in `conv-manager/smart_home_rag/` (manifest, chunker, indexer, retrieval eval).
- Hybrid retrieval (`dense + lexical + parent assembly`) with measured local eval metrics stored in `plan.md`.
- Native embedding support via llama.cpp `/v1/embeddings` (replaces removed Ollama embed-engine).

> **Corpus Rebuild:** Run `startup.bat --rebuild-corpus` to re-clone documentation repos and rebuild the RAG index. For advanced corpus customization, see `conv-manager/smart_home_rag/README.md`.

- Multi-tool orchestration: The assistant can call multiple tools in a single response (e.g., calculate sum AND product).
- Tool router with typed envelopes for:
      - `search_docs` (RAG from smart home corpus)
      - `web_search` (DuckDuckGo real-time search)
      - `get_device_status` (device status lookup)
      - `check_device_compatibility` (compatibility check)
      - `crm_profile_read` (CRM read - supports name, city, location, preferences)
      - `crm_profile_write` (CRM write - supports name, city, location, preferences)
      - `calculator` (math expression evaluation)
      - `url_fetch` (web content retrieval from specific URLs)
- Gateway interception mode that buffers tool-call JSON, executes tools, and streams only user-safe final text.
- CRM persistence: User profiles are stored in SQLite (`/tmp/crm_profiles.db`) for cross-session persistence.

# 7. Conversation Policies
Supported topics:
- Home Assistant configuration and troubleshooting
- Zigbee2MQTT pairing and networking
- ESPHome firmware and sensors
- General smart home networking
- Device compatibility checks
- User profile management (name, city, location, preferences via CRM tools)

Refused topics:
- Pricing negotiation
- Legal complaints or threats
- Off-topic content (coding, politics, and unrelated requests)

# 8. Performance Benchmarks
| Metric | Target | How to measure |
|---|---|---|
| TTFT (time-to-first-token) | ≤ 3.0 s average | `python stress_test.py` — TEST 1 `avg_ttft` |
| Full response time | ≤ 12.0 s average | `python stress_test.py` — TEST 1 `avg_total` |
| Concurrent sessions | 10 simultaneous WebSocket sessions | `python stress_test.py` — TEST 2 `success_count` |
| Over-capacity rejection | Extra connections gracefully rejected | `python stress_test.py` — TEST 3 `pass` |
| Session reset isolation | Post-reset responses are context-free | `python stress_test.py` — TEST 4 `pass` |

Run `python stress_test.py` against a live stack to populate results. Results are saved to `stress_test_results.json`.
For raw llama.cpp model latency (no gateway overhead) run `python benchmark.py`. Results are saved to `benchmark_results.json`.

# 9. API Reference
Public REST (gateway):
- `POST /api/sessions` -> `{ "session_id": "uuid", "token": "hmac" }`
- `DELETE /api/sessions/{session_id}?token=...` -> `{ "success": true }`
- `POST /api/sessions/{session_id}/reset?token=...` -> `{ "success": true }`
- `GET /health` -> `{ "status": "ok" }`

WebSocket:
- `GET /ws/chat/{session_id}`
- Client -> server:
```json
{ "type": "user_message", "content": "Where is my order?" }
```
- Voice control messages:
```json
{ "type": "audio_start" }
```
```json
{ "type": "audio_end" }
```
- Voice selection:
```json
{ "type": "set_voice", "voice": "af_bella" }
```
- Server -> client token stream:
```json
{ "type": "token", "content": "partial text" }
```
- Server -> client ASR updates:
```json
{ "type": "asr_partial", "content": "partial transcript" }
```
```json
{ "type": "asr_final", "content": "final transcript" }
```
- Server -> client voice selection ack:
```json
{ "type": "voice_set", "voice": "af_bella" }
```
- Server completion:
```json
{ "type": "done", "content": "", "timings": { "pipeline_wall_ms": 1234 }, "sources": [{ "source": "home_assistant", "path": "source/_integrations/mqtt.markdown", "title": "Discovery messages and availability" }] }
```
- Server error:
```json
{ "type": "error", "content": "reason" }
```

Internal REST (conv-manager):
- `POST /internal/build-prompt` (returns legacy `prompt` plus role-based `chat_messages`, slot budget metadata, and token estimates)
- `POST /internal/update-history`
- `POST /internal/reset-session`
- `POST /internal/create-session`
- `DELETE /internal/delete-session/{session_id}`
- `POST /internal/tool-router/execute`

llama.cpp boundary:
- `POST /v1/chat/completions` — primary streaming chat path
- `POST /v1/embeddings` — embedding generation (Phase 7 migration complete)

# 10. Voice Features
- Voice input uses browser microphone capture, converts audio to 16kHz Int16 PCM, and streams it over the main chat WebSocket.
- Voice output uses Kokoro ONNX WAV synthesis streamed back as binary WebSocket frames.
- Supported built-in TTS voices include `af_bella`, `af_sarah`, `af_nicole`, and `am_michael`.
- For automated smoke coverage, run `python voice_integration_test.py` against a live stack.

# 11. Postman Collection
`postman_collection.json` is provided in the repository root. Import it in Postman using `Import -> File`, then run requests in order starting from `Create Session` to auto-populate `{{session_id}}`.

# 12. Known Limitations
- Session conversation history is in-memory only and is lost on service restart.
- User CRM profiles are persisted in SQLite at `/tmp/crm_profiles.db` and survive restarts.
- CPU-only inference can take roughly 5-20 seconds depending on host hardware and load.
- WebSocket sessions and session mutation routes are authenticated via an HMAC-SHA256 session token returned by `POST /api/sessions`; connections without a valid token are rejected with code 4401.
- Context window is constrained to the most recent 5 full rounds plus a compressed summary of up to 15 older rounds, with an estimated 1600-token hard budget for the full-context portion.

# 12.1 Performance Tuning Notes
- In this Docker setup, `llm-engine` is typically CPU-only unless GPU passthrough is explicitly configured.
- We strictly use the standard OpenAI parameters via `/v1/chat/completions`.
- Default inference controls:
      - `LLM_TEMPERATURE` (default `0.65`)
      - `LLM_MODEL` (default `gemma-4-E4B-it`)
- You can override these in `docker-compose.yml` under `api-gateway.environment`.
- The `llm-engine` is exposed on `localhost:11434` providing both chat and embedding endpoints.

# 12.2 Optional GPU Mode
- GPU mode is possible when Docker Desktop and drivers support device passthrough.
- Use:
```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```
- Verify in llama.cpp logs that compute is not CPU-only and layers are offloaded.

# 13. Project Structure
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
|- asr-service/
|  |- Dockerfile
|  |- requirements.txt
|  |- main.py
|- frontend/
|  |- Dockerfile
|  |- nginx.conf
|  |- package.json
|  |- src/
|     |- App.jsx
|     |- App.css
|     |- hooks/useWebSocket.js
|     |- hooks/useAudioRecorder.js
|     |- hooks/useAudioPlayer.js
|     |- components/
|        |- WelcomeScreen.jsx
|        |- WelcomeScreen.css
|        |- MessageBubble.jsx
|        |- MessageBubble.css
|        |- ChatWindow.jsx
|        |- ChatWindow.css
|        |- MicButton.jsx
|        |- SessionControls.jsx
|        |- SessionControls.css
|        |- VoiceSelector.jsx
|- tts-service/
|  |- Dockerfile
|  |- requirements.txt
|  |- main.py
|- docker-compose.yml
|- docker-compose.gpu.yml
|- startup.sh
|- startup.bat
|- benchmark.py
|- stress_test.py
|- voice_integration_test.py
|- postman_collection.json
|- README.md
```
