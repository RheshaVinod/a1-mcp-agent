"""MCP connection layer: loads the server manifest, performs tool discovery, and
wraps every discovered tool so protocol failures surface as model-readable text
instead of crashing the request."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool, ToolException
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import BaseModel, ValidationError

log = logging.getLogger("mcp")

# Per-tool ceiling. A hung MCP server must not hold an HTTP request open forever.
TOOL_TIMEOUT_SECONDS = float(os.getenv("MCP_TOOL_TIMEOUT", "60"))

_ENV_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")

# Placeholder defaults for values that are better derived than configured.
# PYTHON_BIN must be *this* interpreter: a bare "python" would resolve against PATH
# and can pick up an unrelated system or Conda interpreter that lacks our packages.
_PLACEHOLDER_DEFAULTS = {"PYTHON_BIN": sys.executable}

# Variables a stdio MCP subprocess needs in order to start at all. The MCP SDK
# replaces the child environment wholesale when `env` is supplied, so anything
# omitted here is simply absent for the child -- including PATH, which npx needs.
_PASSTHROUGH_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "SystemRoot", "TMPDIR")


class NoArguments(BaseModel):
    """Fallback schema for a server that advertises a tool with no input schema."""


def _expand(value: Any) -> Any:
    """Substitute ${VAR} placeholders in the manifest from the process environment."""
    if isinstance(value, str):
        return _ENV_PLACEHOLDER.sub(
            lambda m: os.getenv(m.group(1)) or _PLACEHOLDER_DEFAULTS.get(m.group(1), ""),
            value,
        )
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    return value


def load_connections(config_path: str | Path) -> dict[str, dict[str, Any]]:
    """Read the MCP server manifest and resolve it into langchain-mcp-adapters connections."""
    raw = json.loads(Path(config_path).read_text())
    connections: dict[str, dict[str, Any]] = {}

    for name, spec in raw.items():
        connection = _expand(spec)
        if connection.get("transport") == "stdio":
            child_env = {k: os.environ[k] for k in _PASSTHROUGH_ENV if k in os.environ}
            child_env.update(connection.get("env") or {})
            connection["env"] = child_env
        connections[name] = connection

    return connections


def _root_cause(exc: BaseException) -> BaseException:
    """Unwrap nested ExceptionGroups down to the first leaf exception.

    anyio task groups -- which the MCP stdio transport runs on -- can nest groups
    several deep, so a single unwrap still yields an opaque "unhandled errors in a
    TaskGroup" message.
    """
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _classify(exc: BaseException) -> str:
    """Map an exception onto one of the three failure modes the agent must survive."""
    if isinstance(exc, (ValidationError, json.JSONDecodeError, TypeError, KeyError)):
        return "malformed response"
    if isinstance(exc, ToolException):
        return "tool execution error"
    if isinstance(exc, (ConnectionError, OSError, asyncio.TimeoutError, EOFError)):
        return "connection/transport failure"
    return "tool execution error"


def _normalise(result: Any) -> str:
    """Coerce an MCP tool result into text the LLM can read.

    A server is free to return content blocks, nested dicts, or something that does
    not match its own declared schema; none of those may take the process down.
    """
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(result)


def harden(tool: BaseTool, server_name: str) -> StructuredTool:
    """Wrap one discovered MCP tool with timeout, error capture, and result normalisation.

    The wrapper still performs the real `tools/call` through the adapter -- it only
    decides what happens when that call goes wrong.
    """

    async def _invoke(**kwargs: Any) -> str:
        try:
            result = await asyncio.wait_for(tool.ainvoke(kwargs), TOOL_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            raise
        except BaseExceptionGroup as group:  # anyio task groups wrap stdio transport faults
            inner = _root_cause(group)
            kind = _classify(inner)
            log.warning("%s.%s failed (%s): %s", server_name, tool.name, kind, inner)
            return f"MCP {kind} calling '{tool.name}' on the {server_name} server: {inner}"
        except Exception as exc:
            kind = _classify(exc)
            log.warning("%s.%s failed (%s): %s", server_name, tool.name, kind, exc)
            return f"MCP {kind} calling '{tool.name}' on the {server_name} server: {exc}"

        try:
            return _normalise(result)
        except Exception as exc:
            log.warning("%s.%s returned an unreadable result: %s", server_name, tool.name, exc)
            return f"MCP malformed response from '{tool.name}' on the {server_name} server: {exc}"

    return StructuredTool(
        name=tool.name,
        description=f"[{server_name}] {tool.description}",
        args_schema=tool.args_schema or NoArguments,
        coroutine=_invoke,
    )


async def discover_tools(
    connections: dict[str, dict[str, Any]],
) -> tuple[list[StructuredTool], dict[str, list[str]], dict[str, str]]:
    """Run MCP `tools/list` against every configured server.

    Each server is probed independently so that one unreachable server degrades the
    agent's capabilities instead of failing startup.

    Returns the hardened tools, the tool names discovered per server, and the
    discovery error per server that could not be reached.
    """
    client = MultiServerMCPClient(connections)
    tools: list[StructuredTool] = []
    discovered: dict[str, list[str]] = {}
    failures: dict[str, str] = {}

    for name in connections:
        try:
            server_tools = await client.get_tools(server_name=name)
        except BaseExceptionGroup as group:
            inner = _root_cause(group)
            failures[name] = f"{type(inner).__name__}: {inner}"
            log.error("MCP discovery failed for %s: %s", name, inner)
            continue
        except Exception as exc:
            failures[name] = f"{type(exc).__name__}: {exc}"
            log.error("MCP discovery failed for %s: %s", name, exc)
            continue

        discovered[name] = [t.name for t in server_tools]
        tools.extend(harden(t, name) for t in server_tools)
        log.info("MCP %s exposed %d tools: %s", name, len(server_tools), discovered[name])

    return tools, discovered, failures
