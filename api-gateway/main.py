from __future__ import annotations

import logging
import os

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from llm_client import OllamaClient
from session_router import router as session_router
from websocket_handler import router as websocket_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api-gateway")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    llm = OllamaClient()
    healthy = await llm.health_check()
    if not healthy:
        logger.warning("action=ollama_health_check status=unhealthy")
    elif os.getenv("OLLAMA_WARMUP_ON_STARTUP", "true").lower() in {"1", "true", "yes"}:
        warmed = await llm.warmup()
        if warmed:
            logger.info("action=ollama_warmup status=ready")
        else:
            logger.warning("action=ollama_warmup status=failed")
    yield


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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
