# Plan: Customer Support Conversational AI

## Objective
Implement a local, Dockerized e-commerce customer-support conversational AI system with four services and strict policy-first behavior.

## Deliverables
- `conv-manager` FastAPI microservice (session/history/prompt/policy).
- `api-gateway` FastAPI microservice (session routes + WebSocket + Ollama client).
- `frontend` React 18 + Vite chat interface.
- Docker artifacts: per-service Dockerfiles, `docker-compose.yml`, `startup.sh`, `nginx.conf`.
- QA artifacts: `benchmark.py`, `stress_test.py`, `postman_collection.json`, `README.md`.

## Acceptance Criteria
- Endpoints and WebSocket contract match defined interface paths.
- Streaming token flow works from gateway to frontend.
- Session lifecycle routes create/reset/delete sessions.
- No RAG/tools/external APIs are used.
- Logging avoids message content and only tracks metadata.

## Edge Cases & Constraints
- CPU-only environment, Windows host with 16 GB RAM.
- Max 10 concurrent WebSocket connections.
- Block repeated/injection/overlength user input.
- Keep context window bounded by turn/token trimming.
- Never expose internal hostnames in error responses.

## Implementation Steps
- [x] Step 1: Scaffold directory structure and baseline files.
- [x] Step 2: Implement `conv-manager` modules and main API.
- [x] Step 3: Implement `api-gateway` client, routes, WebSocket handler, app wiring.
- [x] Step 4: Implement React frontend and CSS components.
- [x] Step 5: Add Dockerfiles, compose, startup script, nginx config.
- [x] Step 6: Add benchmark, stress test, Postman collection, README.
- [x] Step 7: Run sanity validation and report gaps.

## Files & APIs Touched
- `conv-manager/*`
- `api-gateway/*`
- `frontend/*`
- `docker-compose.yml`
- `startup.sh`
- `benchmark.py`
- `stress_test.py`
- `postman_collection.json`
- `README.md`

## Manual QA / Verification Steps
- Start stack: `bash startup.sh`.
- Check health: `GET http://localhost:8000/health`.
- Verify session lifecycle with REST routes.
- Open UI at `http://localhost:3000`, send message, verify streamed tokens and done event.
- Run `python benchmark.py` and `python stress_test.py` from repo root.

## Notes / Decisions
- Locked decisions from architecture document are treated as final and enforced in prompts/policies.

## Phase 2 - Prompt and Memory Tuning
- [x] Introduce hybrid memory policy: 20 rounds total context, with recent 5 rounds full and prior 15 rounds summarized.
- [x] Add same-model summarization call to compress older rounds for high signal, low noise context.
- [x] Update system prompt for less rigid responses while preserving policy boundaries.
- [x] Raise generation temperature to improve response diversity and reduce repetitiveness.
