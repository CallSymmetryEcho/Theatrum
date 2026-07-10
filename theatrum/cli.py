"""Theatrum CLI — argparse only (dependency budget: mcp + pyyaml)."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, core, index as _index
from .connect import connect_host, disconnect_host


def _print(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def cmd_init(args: argparse.Namespace) -> int:
    v = core.init_vault()
    _index.ensure_index()
    core.write_map()
    _print(f"initialized vault at {v}")
    return 0


def cmd_remember(args: argparse.Namespace) -> int:
    content = args.content
    if not content:
        content = sys.stdin.read()
    if not content.strip():
        _print("error: empty content")
        return 2
    project = args.project
    if args.scope == "project" and not project:
        project = core.detect_project()
    tags = _split_csv(args.tags)
    derived = _split_csv(args.derived_from)
    mem = core.remember(
        content=content,
        type=args.type,
        scope=args.scope,
        project=project,
        tags=tags,
        source=args.source,
        derived_from=derived,
        confidence=args.confidence,
        title_hint=args.title,
    )
    _print(f"remembered {mem.id} → {mem.path}")
    return 0


def cmd_recall(args: argparse.Namespace) -> int:
    project = args.project
    if args.scope == "project" and not project:
        project = core.detect_project()
    hits = _index.recall(
        args.query,
        scope=args.scope,
        project=project,
        limit=args.limit,
    )
    if not hits:
        _print("no matches")
        return 0
    for h in hits:
        m = h.memory
        _print(f"{m.id}\t{m.type}\t{m.scope}\t{m.project or '-'}\tscore={h.score:.4f}\t{m.title()}")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    project = args.project or core.detect_project()
    text = _index.build_context(
        args.query,
        budget=args.budget,
        deep=args.deep,
        project=project,
    )
    sys.stdout.write(text)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    # Local import so ``theatrum --help`` doesn't require mcp installed.
    from .server import serve
    serve()
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    result = connect_host(args.host)
    _print(result)
    return 0


def cmd_disconnect(args: argparse.Namespace) -> int:
    result = disconnect_host(args.host)
    _print(result)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    report = core.doctor()
    _print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("index_ok") and report.get("vault_exists") else 1


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="theatrum",
        description="Local-first memory control plane for AI agents.",
    )
    p.add_argument("--version", action="version", version=f"theatrum {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="initialize the vault").set_defaults(func=cmd_init)

    r = sub.add_parser("remember", help="save a memory")
    r.add_argument("content", nargs="?", help="memory body (defaults to stdin)")
    r.add_argument("--type", required=True, choices=sorted(core.VALID_TYPES))
    r.add_argument("--scope", required=True, choices=sorted(core.VALID_SCOPES))
    r.add_argument("--project", help="project id (auto-detected when scope=project)")
    r.add_argument("--tags", help="comma-separated tags")
    r.add_argument("--source", default="user_requested", choices=sorted(core.VALID_SOURCES))
    r.add_argument("--derived-from", dest="derived_from", help="comma-separated memory ids")
    r.add_argument("--confidence", default="medium", choices=sorted(core.VALID_CONFIDENCE))
    r.add_argument("--title", help="optional title hint used to build the id slug")
    r.set_defaults(func=cmd_remember)

    rc = sub.add_parser("recall", help="ranked search")
    rc.add_argument("query")
    rc.add_argument("--scope", choices=sorted(core.VALID_SCOPES))
    rc.add_argument("--project", help="project id (auto-detected when scope=project)")
    rc.add_argument("--limit", type=int, default=10)
    rc.set_defaults(func=cmd_recall)

    c = sub.add_parser("context", help="MAP.md header + top memories under a budget")
    c.add_argument("query")
    c.add_argument("--budget", type=int, default=2000)
    c.add_argument("--deep", action="store_true")
    c.add_argument("--project", help="project id (default: auto-detected)")
    c.set_defaults(func=cmd_context)

    sub.add_parser("serve", help="run the MCP stdio server").set_defaults(func=cmd_serve)

    cn = sub.add_parser("connect", help="wire the MCP server into a host")
    cn.add_argument("host", choices=["claude", "codex"])
    cn.set_defaults(func=cmd_connect)

    dc = sub.add_parser("disconnect", help="unwire the MCP server from a host")
    dc.add_argument("host", choices=["claude", "codex"])
    dc.set_defaults(func=cmd_disconnect)

    sub.add_parser("doctor", help="health report").set_defaults(func=cmd_doctor)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
