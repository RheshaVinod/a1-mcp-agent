"""Verification for the MCP layer. Runs without an LLM key.

Covers tool discovery against every configured server plus the three failure modes
the assignment requires the agent to survive: connection/transport failures, tool
execution errors, and malformed or invalid responses.

    python test_mcp.py
"""

from __future__ import annotations

import asyncio
import os
import sys

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from mcp_runtime import discover_tools, harden, load_connections


class _NoArgs(BaseModel):
    pass

WORKSPACE = os.getenv("MCP_FILESYSTEM_ROOT", os.path.abspath("workspace"))
passed, failed = 0, 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


async def test_discovery() -> list[StructuredTool]:
    print("\n[1] tools/list against every configured server")
    connections = load_connections(os.getenv("MCP_CONFIG_PATH", "mcp_config.json"))
    tools, discovered, failures = await discover_tools(connections)

    check("all configured servers reachable", not failures, str(failures))
    check("at least 3 servers discovered", len(discovered) >= 3, str(list(discovered)))
    for server, names in discovered.items():
        check(f"{server} exposed tools", bool(names), "(none)")
    check("every tool carries an input schema", all(t.args_schema for t in tools))
    return tools


async def test_successful_call(tools: list[StructuredTool]) -> None:
    print("\n[2] tools/call round trip")
    read = next(t for t in tools if t.name == "read_text_file")
    result = await read.ainvoke({"path": os.path.join(WORKSPACE, "notes.txt")})
    check("filesystem read returned file contents", "CSCI 599" in result, result[:120])


async def test_tool_execution_error(tools: list[StructuredTool]) -> None:
    print("\n[3] failure mode: tool execution error")
    read = next(t for t in tools if t.name == "read_text_file")
    result = await read.ainvoke({"path": "/etc/definitely-not-allowed.txt"})
    check("error captured as text, not an exception", isinstance(result, str))
    check("error is labelled for the model", "MCP tool execution error" in result, result[:120])


async def test_transport_failure() -> None:
    print("\n[4] failure mode: connection/transport failure")
    dead = {
        "dead": {
            "transport": "stdio",
            "command": "/nonexistent/mcp-server-binary",
            "args": [],
        }
    }
    tools, discovered, failures = await discover_tools(dead)
    check("unreachable server does not raise", True)
    check("unreachable server reported as a failure", "dead" in failures, str(failures))
    check("no tools harvested from a dead server", not tools)


async def test_malformed_response() -> None:
    print("\n[5] failure mode: malformed / unserialisable response")

    class Unserialisable:
        def __repr__(self) -> str:
            return "<opaque object>"

    async def _returns_garbage(**_: object) -> object:
        return Unserialisable()

    async def _raises_typeerror(**_: object) -> object:
        raise TypeError("response did not match the declared schema")

    garbage = harden(
        StructuredTool(
            name="garbage", description="d", args_schema=_NoArgs, coroutine=_returns_garbage
        ),
        "fake",
    )
    result = await garbage.ainvoke({})
    check("non-JSON result coerced to text", isinstance(result, str), repr(result))

    invalid = harden(
        StructuredTool(
            name="invalid", description="d", args_schema=_NoArgs, coroutine=_raises_typeerror
        ),
        "fake",
    )
    result = await invalid.ainvoke({})
    check("schema mismatch classified as malformed", "malformed response" in result, result[:120])


async def main() -> int:
    tools = await test_discovery()
    await test_successful_call(tools)
    await test_tool_execution_error(tools)
    await test_transport_failure()
    await test_malformed_response()
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
