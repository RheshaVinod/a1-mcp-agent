"""FastAPI entrypoint for the CSCI 599 Assignment 1 MCP agent service."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent import answer, build_agent
from mcp_runtime import discover_tools, load_connections

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("service")


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


class ChatResponse(BaseModel):
    response: str


# Populated during startup; read by the request handlers.
runtime: dict = {"graph": None, "tools": {}, "failures": {}, "error": None}


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Discover MCP tools once, then compile the agent around them."""
    config_path = os.getenv("MCP_CONFIG_PATH", "mcp_config.json")
    try:
        connections = load_connections(config_path)
        tools, discovered, failures = await discover_tools(connections)
        runtime["tools"] = discovered
        runtime["failures"] = failures
        runtime["graph"] = build_agent(tools)
        log.info(
            "Agent ready: %d tools from %d/%d servers",
            sum(len(v) for v in discovered.values()),
            len(discovered),
            len(connections),
        )
    except Exception as exc:  # keep the service answerable so failures are diagnosable
        runtime["error"] = f"{type(exc).__name__}: {exc}"
        log.exception("Startup failed")
    yield


app = FastAPI(title="CSCI 599 A1 — MCP Agent", lifespan=lifespan)


@app.get("/")
async def index():
    """Service and MCP discovery status."""
    return {
        "service": "csci599-a1",
        "ready": runtime["graph"] is not None,
        "mcp_servers": runtime["tools"],
        "mcp_discovery_failures": runtime["failures"],
        "startup_error": runtime["error"],
    }


@app.get("/health")
async def health():
    """Liveness probe. Not /healthz -- Cloud Run's frontend intercepts that path and
    it never reaches the container."""
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Answer one turn, keyed to the caller's session_id for conversational memory."""
    if runtime["graph"] is None:
        return JSONResponse(
            status_code=503,
            content={"response": f"Agent unavailable: {runtime['error']}"},
        )

    try:
        text = await answer(runtime["graph"], request.query, request.session_id)
    except Exception as exc:
        log.exception("Turn failed for session %s", request.session_id)
        return JSONResponse(
            status_code=500,
            content={"response": f"The agent could not complete this turn: {exc}"},
        )

    return ChatResponse(response=text)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
