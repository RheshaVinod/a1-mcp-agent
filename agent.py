"""LangGraph ReAct agent: an LLM that reasons over MCP-discovered tools and keeps
per-session conversational state in a LangGraph checkpointer."""

from __future__ import annotations

import logging
import os

from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage
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
- Stop calling tools as soon as you have enough to answer. "Fetch the page" means one
  page, normally the best search result; do not crawl further pages unless asked.
  Fetch it once with max_length around 20000 rather than paging through it with
  start_index. Most questions need no more than three tool calls.
- A tool result beginning with "MCP " and naming a failure is an error, not data.
  Say what failed, then answer as best you can without it or try a different tool.
- Cite which tool and which server produced any external fact you report.
"""


# Tool results allowed per turn before the model is told to answer. Without a cap,
# an open-ended request ("fetch the spec and summarize it") can keep crawling linked
# pages until LangGraph's recursion limit replaces the answer with an apology.
TOOL_CALL_BUDGET = 6

BUDGET_REACHED = HumanMessage(
    content="[Tool budget reached] Do not call any more tools. Write your final "
    "answer now from the information already gathered, and say what you could not check."
)


def enforce_tool_budget(state: dict) -> dict:
    """pre_model_hook: once this turn has used its tool budget, tell the model to answer.

    The note goes only into this LLM call's input, never into the saved history.
    """
    messages: list[AnyMessage] = state["messages"]
    turn_start = max(
        (i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=0
    )
    used = sum(isinstance(m, ToolMessage) for m in messages[turn_start:])
    if used < TOOL_CALL_BUDGET:
        return {"llm_input_messages": messages}
    log.info("Tool budget of %d reached; asking the model to answer", TOOL_CALL_BUDGET)
    return {"llm_input_messages": [*messages, BUDGET_REACHED]}


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
        pre_model_hook=enforce_tool_budget,
        checkpointer=MemorySaver(),
    )


async def answer(graph, query: str, session_id: str) -> str:
    """Run one turn through the graph under the given session's memory thread."""
    state = await graph.ainvoke(
        {"messages": [HumanMessage(content=query)]},
        config={"configurable": {"thread_id": session_id}, "recursion_limit": 40},
    )
    final = state["messages"][-1]
    return final.content if isinstance(final.content, str) else str(final.content)
