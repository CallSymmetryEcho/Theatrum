"""
Theatrum MCP server (stdio, FastMCP).

Thin wrappers over ``core``. The MCP server cannot verify the ``source`` field —
it trusts the calling agent. Anti-pollution stays with inbox review + Git diff.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import core, index as _index


mcp = FastMCP("theatrum")


@mcp.tool()
def memory_remember(
    content: str,
    type: str,
    scope: str,
    project: str | None = None,
    tags: list[str] | None = None,
    source: str = "user_requested",
    derived_from: list[str] | None = None,
    confidence: str = "medium",
) -> dict[str, Any]:
    """
    Save a memory.

    - ``source="user_requested"`` → status ``active``, filed under scope dir.
    - ``source="agent_inferred"`` → status ``proposed``, filed under ``inbox/``
      and EXCLUDED from recall/context results until reviewed.
    """
    if scope == "project" and not project:
        # Agents should pass ``project`` explicitly; fall back to detection so
        # single-agent flows still work.
        project = core.detect_project()
    try:
        mem = core.remember(
            content=content,
            type=type,
            scope=scope,
            project=project,
            tags=list(tags or []),
            source=source,
            derived_from=list(derived_from or []),
            confidence=confidence,
        )
    except ValueError as exc:
        return {"error": str(exc)}
    return {
        "id": mem.id,
        "path": str(mem.path) if mem.path else None,
        "status": mem.status,
        "scope": mem.scope,
        "project": mem.project,
    }


@mcp.tool()
def memory_recall(
    query: str,
    scope: str | None = None,
    project: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Ranked search. Project isolation is a hard filter, not a boost.
    When ``project`` is None, only global-scope memories are returned.
    """
    hits = _index.recall(query, scope=scope, project=project, limit=limit)
    return [
        {
            "id": h.memory.id,
            "type": h.memory.type,
            "scope": h.memory.scope,
            "project": h.memory.project,
            "title": h.memory.title(),
            "score": h.score,
            "path": str(h.memory.path) if h.memory.path else None,
        }
        for h in hits
    ]


@mcp.tool()
def memory_context(
    query: str,
    budget: int = 2000,
    deep: bool = False,
    project: str | None = None,
) -> str:
    """MAP.md header + top memories packed under ``budget`` tokens (chars/4).
    When ``project`` is None, only global-scope memories are included.
    """
    return _index.build_context(query, budget=budget, deep=deep, project=project)


@mcp.tool()
def memory_feedback(ids: list[str], outcome: str) -> dict[str, Any]:
    """Increment ``used``/``dead_end`` counters and reindex."""
    updated = core.apply_feedback(ids, outcome)
    return {"updated": [m.id for m in updated], "outcome": outcome}


def serve() -> None:
    _index.ensure_index()
    mcp.run()
