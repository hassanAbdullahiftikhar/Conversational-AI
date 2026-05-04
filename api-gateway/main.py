from __future__ import annotations

import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api-gateway")

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from llm_client import LlmClient, get_llm_http_client
from session_router import router as session_router
from websocket_handler import router as websocket_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api-gateway")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    llm = LlmClient()
    healthy = await llm.health_check()
    if not healthy:
        logger.warning("action=llm_health_check status=unhealthy")
    else:
        logger.info("action=llm_health_check status=ready")
    yield
    # Teardown
    try:
        client = await get_llm_http_client()
        await client.aclose()
    except Exception:
        pass
    logger.info("action=gateway_shutdown clients_closed")


from eval_router import router as eval_router

app = FastAPI(title="api-gateway", lifespan=lifespan)

_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

app.include_router(session_router)
app.include_router(websocket_router)
app.include_router(eval_router)

@app.post("/chat")
async def chat_rest(request: Request):
    """REST endpoint for evaluations. Implementation will follow in websocket_handler refactor."""
    from websocket_handler import run_chat_rest
    return await run_chat_rest(request)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
