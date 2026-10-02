"""LangGraph ReAct agent: an LLM that reasons over MCP-discovered tools and keeps
per-session conversational state in a LangGraph checkpointer."""

from __future__ import annotations

import logging
import os

from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

log = logging.getLogger("agent")

SYSTEM_PROMPT = """You are a research assistant for a graduate agentic-AI course.

You have tools from three MCP servers. Choose deliberately:
- filesystem tools: read, write, list, or search files in the local workspace.
- tavily search tools: find current or external information you do not already know.
- fetch tool: retrieve the contents of one specific URL the user gave you, or a URL
  a search result surfaced.

Rules:
- If the question is general knowledge, reasoning, or about your own conversation
  history, answer directly. Do not call a tool just to appear busy.
- If one tool's output is not enough, call another. Chaining is expected: search for
  a page, then fetch it; or read a file, then search for what it references.
- A tool result beginning with "MCP " and naming a failure is an error, not data.
  Say what failed, then answer as best you can without it or try a different tool.
- Cite which tool and which server produced any external fact you report.
"""


def build_llm() -> ChatOpenAI:
    """Construct the chat model.

    OPENAI_BASE_URL points at NVIDIA NIM's OpenAI-compatible endpoint by default, so
    the same code runs against NIM or OpenAI depending on environment alone.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set; the agent has no LLM backend.")

    model = os.getenv("LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
    base_url = os.getenv("OPENAI_BASE_URL") or None
    log.info("LLM backend: model=%s base_url=%s", model, base_url or "api.openai.com")

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0,
        timeout=90,
        max_retries=2,
    )


def build_agent(tools: list[StructuredTool]):
    """Compile the ReAct graph with an in-memory checkpointer.

    MemorySaver is LangGraph's built-in short-term memory primitive. State is keyed by
    thread_id, which the HTTP layer sets to the caller's session_id. Per the assignment,
    this lives only as long as the Cloud Run instance.
    """
    return create_react_agent(
        build_llm(),
        tools,
        prompt=SYSTEM_PROMPT,
        checkpointer=MemorySaver(),
    )


async def answer(graph, query: str, session_id: str) -> str:
    """Run one turn through the graph under the given session's memory thread."""
    state = await graph.ainvoke(
        {"messages": [HumanMessage(content=query)]},
        config={"configurable": {"thread_id": session_id}, "recursion_limit": 24},
    )
    final = state["messages"][-1]
    return final.content if isinstance(final.content, str) else str(final.content)
