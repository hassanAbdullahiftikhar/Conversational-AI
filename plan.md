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

---

## Phase 3 — Voice Extension

### Status
Historical only. This phase was superseded by Phase 4 below and is no longer the current implementation.

### Historical Summary
- Phase 3 introduced the first local voice stack and added ASR/TTS services to the project.
- The current codebase does not use the original Phase 3 model contracts, voice names, or verification steps.
- Use the Phase 4 section below as the source of truth for the active voice architecture, runtime behavior, and QA expectations.

---

## Phase 4 — Instant Voice & Streaming ASR Overhaul

### Objective
Replace the Phase 3 GPU-heavy voice stack with CPU-only ONNX-native services and true streaming browser microphone transport.

### Architecture Decisions
- TTS moves to `kokoro-onnx` with local model artifacts baked into the image.
- ASR moves to Moonshine's ONNX-native streaming API via the supported Python `moonshine-voice` package.
- Frontend microphone transport changes from whole-blob WebM upload to raw 16kHz Int16 PCM websocket frames.
- Gateway proxies a downstream ASR websocket and surfaces `asr_partial` / `asr_final` events upstream.

### Constraints
- Ollama remains the only GPU/VRAM consumer.
- ASR and TTS stay CPU-only.
- No disk writes for ASR streaming.
- Partial transcript updates must be visible while the mic is held.

### Implementation Steps
- [x] Step 4.1: Rewrite `tts-service` around Kokoro ONNX.
- [x] Step 4.2: Rewrite `asr-service` around Moonshine streaming transcription.
- [x] Step 4.3: Replace gateway voice upload flow with websocket proxying.
- [x] Step 4.4: Replace frontend blob recording with continuous PCM chunk streaming.
- [x] Step 4.5: Update compose settings and plan documentation for CPU-only voice services.

### Manual QA / Verification Steps
- Build the stack with `docker compose up -d --build`.
- Verify `GET http://localhost:8002/health` returns Moonshine service health.
- Verify `GET http://localhost:8003/health` returns Kokoro service health.
- Hold the mic button in the UI and confirm partial transcript text appears live.
- Release the mic button and confirm the final transcript is added as a user turn.
- Confirm the assistant response streams normally after voice input completes.

---

## Phase 5 — Frontend Product Redesign Program

### Objective
Transform the current functional chat UI into a product-grade conversational surface with stronger visual identity, richer motion, better control affordances, and safer room for future enhancements without breaking the working text and voice pipeline.

### Non-Negotiable Guardrails
- Preserve all current working flows for text chat, streamed responses, microphone capture, ASR partial/final updates, TTS playback, interruption, per-message mute, and session reset/new-chat behavior.
- Keep the redesign incremental so each slice can be validated with a production build and live manual smoke testing.
- Favor layered upgrades over a full rewrite so functional regressions stay easy to isolate.

### Visual Direction
- Move away from the current utilitarian dashboard feel toward a more premium conversational workspace.
- Introduce a clearer design system with stronger typography, richer surfaces, more deliberate spacing, and ambient depth.
- Treat voice as a first-class feature in the visual hierarchy rather than an auxiliary setting row.

### Preferred Tooling Path
- Introduce a component primitive layer inspired by `shadcn/ui` using Radix-based patterns where it improves accessibility and consistency.
- Add motion deliberately with `framer-motion` for page-load choreography, list transitions, status changes, and control feedback.
- Preserve existing React component boundaries while progressively replacing coarse CSS with a more intentional tokenized system.

### Phase 5.1 — Foundation and Design System
- [x] Establish visual tokens for typography, color, spacing, radius, shadow, and motion timing.
- [ ] Choose and integrate a more expressive font pairing appropriate for a premium support product.
- [x] Add a component primitive layer for buttons, badges, toggles, segmented controls, cards, tooltips, and sheets/dialogs.
- [ ] Normalize focus states, hover states, and disabled states across all interactive controls.

### Phase 5.2 — Shell and Layout Redesign
- [x] Redesign the app shell so it feels wider, lighter, and more immersive on desktop without hurting mobile use.
- [x] Rebuild the header into a composed top bar with clearer brand hierarchy, status, and voice controls.
- [x] Improve the input dock into a more deliberate action area with stronger affordances for typing and voice capture.
- [x] Add responsive breakpoints so controls shift gracefully between desktop, tablet, and mobile layouts.

### Phase 5.3 — Chat Stream and Message Cards
- [x] Redesign message bubbles into more polished cards with stronger spacing, hierarchy, and action placement.
- [ ] Add compact action rails for copy, mute, replay, and future actions without cluttering the transcript.
- [x] Improve long-response readability with better width rules, rhythm, and emphasis handling.
- [x] Introduce tasteful motion for message entry, assistant streaming, and action confirmation.

### Phase 5.4 — Voice Experience Surface
- [x] Turn voice preferences into a dedicated control cluster with clearer grouping and easier discoverability.
- [x] Add stronger speaking, listening, muted, and disabled-state cues so audio behavior is always legible.
- [ ] Add replay-on-demand for assistant messages using the current voice and speed preferences.
- [x] Upgrade the live partial transcript surface so recording feels active and responsive rather than bolted on.

### Phase 5.5 — Welcome and Empty-State Experience
- [x] Rework the welcome screen into a more branded, animated onboarding surface with curated quick prompts.
- [x] Add light product framing so first-time users immediately understand text, voice, and session features.
- [x] Use motion and layout transitions to make the shift from welcome state to active conversation feel intentional.

### Phase 5.6 — Motion, Accessibility, and QA
- [ ] Add `framer-motion` transitions for message appearance, control feedback, and state changes without over-animating core chat flows.
- [ ] Improve keyboard navigation, screen-reader labels, hit targets, and reduced-motion behavior.
- [ ] Add targeted frontend coverage for voice preferences, message actions, and key interaction states.
- [ ] Validate each redesign slice with `npm run build` plus live text and voice smoke checks.

### Immediate Execution Slice
- [x] Wire backend/frontend speed control.
- [x] Expand supported speed range to `0.25x` through `3.0x`.
- [x] Add global speech toggle.
- [x] Refine voice controls into a dedicated styled component.
- [x] Add message copy action.
- [x] Relax shell and bubble width constraints so short and medium user prompts do not wrap prematurely.
