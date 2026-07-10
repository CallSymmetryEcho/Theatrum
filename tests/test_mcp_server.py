"""
Protocol-layer tests for the Theatrum MCP server over real stdio.

These tests spawn the server as a subprocess, drive it through the MCP
client (initialize / list_tools / call_tool), and assert the protocol
round-trip works correctly.  No pytest-asyncio — async code is wrapped
with asyncio.run() inside sync test functions.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

from mcp import ClientSession, StdioServerParameters, stdio_client


# ---------------------------------------------------------------------------
# Helper — build server params pointing at a fresh vault directory
# ---------------------------------------------------------------------------

def _server_params(vault_dir: str) -> StdioServerParameters:
    """Return StdioServerParameters that launch the theatrum serve command."""
    script = (
        "from theatrum.cli import main; import sys; "
        "sys.argv=['theatrum','serve']; raise SystemExit(main())"
    )
    return StdioServerParameters(
        command=sys.executable,
        args=["-c", script],
        env={**os.environ, "THEATRUM_HOME": vault_dir},
    )


# ---------------------------------------------------------------------------
# Test 1: initialize + list_tools — exactly four tools exposed
# ---------------------------------------------------------------------------

def test_mcp_list_tools(tmp_path):
    vault = str(tmp_path / "theatrum")

    async def _run():
        params = _server_params(vault)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [t.name for t in result.tools]

    tool_names = asyncio.run(_run())
    assert set(tool_names) == {
        "memory_remember",
        "memory_recall",
        "memory_context",
        "memory_feedback",
    }, f"Unexpected tool list: {tool_names}"


# ---------------------------------------------------------------------------
# Test 2: round-trip remember → recall, plus path-traversal error result
# ---------------------------------------------------------------------------

def test_mcp_remember_recall_and_traversal_error(tmp_path):
    vault = str(tmp_path / "theatrum")

    async def _run():
        params = _server_params(vault)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # --- remember a global memory ---
                remember_result = await session.call_tool(
                    "memory_remember",
                    arguments={
                        "content": "# mcp protocol test\nstdio round-trip works.",
                        "type": "lesson",
                        "scope": "global",
                        "source": "user_requested",
                    },
                )
                assert not remember_result.isError, (
                    f"memory_remember returned an error: {remember_result}"
                )
                payload = json.loads(remember_result.content[0].text)
                mem_id = payload["id"]
                assert mem_id, "memory_remember returned empty id"
                assert payload["scope"] == "global"

                # --- recall it back ---
                recall_result = await session.call_tool(
                    "memory_recall",
                    arguments={"query": "mcp protocol stdio round-trip"},
                )
                assert not recall_result.isError, (
                    f"memory_recall returned an error: {recall_result}"
                )
                # FastMCP serializes a list[dict] result as one TextContent per item.
                hits = [
                    json.loads(c.text)
                    for c in recall_result.content
                    if c.type == "text"
                ]
                hit_ids = [h["id"] for h in hits]
                assert mem_id in hit_ids, (
                    f"Remembered id {mem_id!r} not found in recall hits: {hit_ids}"
                )

                # --- path traversal: project="../evil" must return error dict, not crash ---
                traversal_result = await session.call_tool(
                    "memory_remember",
                    arguments={
                        "content": "# traversal\nevil attempt.",
                        "type": "lesson",
                        "scope": "project",
                        "project": "../evil",
                        "source": "user_requested",
                    },
                )
                # The server should NOT crash the protocol; it should return
                # either an MCP-level error or a JSON dict with "error" key.
                if traversal_result.isError:
                    # MCP-level error — acceptable
                    pass
                else:
                    body = json.loads(traversal_result.content[0].text)
                    assert "error" in body, (
                        f"Expected 'error' key for traversal attempt, got: {body}"
                    )

                return True

    ok = asyncio.run(_run())
    assert ok
