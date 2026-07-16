"""Theatrum CLI — argparse only (dependency budget: mcp + pyyaml)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, core, index as _index
from .connect import connect_host, disconnect_host


def _print(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def cmd_init(args: argparse.Namespace) -> int:
    v = core.init_vault()
    _index.ensure_index()
    core.write_map()
    _print(f"initialized vault at {v}")
    if not (core.vault_dir() / ".git").exists():
        _print(f"tip: cd {v} && git init   # git is the audit trail and the recovery path")
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


def cmd_review(args: argparse.Namespace) -> int:
    proposed = [m for m in core.iter_all_memories() if m.status == "proposed"]
    if not proposed:
        _print("inbox is empty")
        return 0
    for m in proposed:
        _print(f"{m.id}\t{m.type}\t{m.scope}\t{m.project or '-'}\t{m.created}\t{m.title()}")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    approved = core.approve(args.ids)
    approved_ids = {m.id for m in approved}
    for m in approved:
        _print(f"approved {m.id} → {m.path}")
    for mem_id in args.ids:
        if mem_id not in approved_ids:
            _print(f"skipped {mem_id} (not found or not proposed)")
    return 0 if approved_ids == set(args.ids) else 1


def cmd_import(args: argparse.Namespace) -> int:
    from . import importer

    path = Path(args.path).expanduser()
    if not path.exists():
        _print(f"error: path not found: {path}")
        return 2

    project = args.project
    if args.scope == "project" and not project:
        project = core.detect_project(path if path.is_dir() else path.parent)

    result = importer.run_import(
        args.kind, path,
        scope=args.scope, project=project, type=args.type, yes=args.yes,
    )
    imported = result["imported"]
    duplicates = result["duplicates"]
    secrets = result["secrets"]

    if args.yes:
        for mem_id, _rel in imported:
            _print(f"imported {mem_id} → inbox")
    else:
        for title, rel in imported:
            _print(f"+ {title}  ({rel})")
        for rel in duplicates:
            _print(f"~ dup: {rel}")
        for rel in secrets:
            _print(f"! secret: {rel}")

    n = len(imported)
    m = len(duplicates)
    k = len(secrets)
    if args.yes:
        _print(f"imported {n} (skipped {m} duplicate, {k} secret-flagged)")
        _print("next: theatrum review")
    else:
        _print(f"would import {n} ({m} duplicate, {k} secret-flagged skipped)")
        _print("re-run with --yes to write into inbox/ for review")
    return 0


def cmd_sync_init(args: argparse.Namespace) -> int:
    from . import sync as sync_mod

    report = sync_mod.initialize(
        args.url,
        remote=args.remote,
        branch=args.branch,
    )
    _print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def cmd_sync_status(args: argparse.Namespace) -> int:
    from . import sync as sync_mod

    _print(json.dumps(sync_mod.sync_status(), indent=2, sort_keys=True))
    return 0


def cmd_sync_run(args: argparse.Namespace) -> int:
    from . import sync as sync_mod

    result = sync_mod.run_sync(
        remote=args.remote,
        branch=args.branch,
        message=args.message,
        no_push=args.no_push,
        allow_secrets=args.allow_secrets,
    )
    _print(json.dumps({
        "remote": result.remote,
        "branch": result.branch,
        "committed": result.committed,
        "pulled": result.pulled,
        "pushed": result.pushed,
        "rebuilt": result.rebuilt,
    }, indent=2, sort_keys=True))
    return 0


def cmd_forget(args: argparse.Namespace) -> int:
    removed = core.forget(args.ids)
    removed_ids = set(removed)
    for mem_id in removed:
        _print(f"forgot {mem_id}")
    for mem_id in args.ids:
        if mem_id not in removed_ids:
            _print(f"skipped {mem_id} (not found)")
    return 0 if removed_ids == set(args.ids) else 1


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

    sub.add_parser("review", help="list proposed (inbox) memories").set_defaults(func=cmd_review)

    ap = sub.add_parser("approve", help="promote proposed memories to active")
    ap.add_argument("ids", nargs="+", help="memory ids to approve")
    ap.set_defaults(func=cmd_approve)

    fg = sub.add_parser("forget", help="delete memories permanently (git is recovery)")
    fg.add_argument("ids", nargs="+", help="memory ids to forget")
    fg.set_defaults(func=cmd_forget)

    im = sub.add_parser("import", help="read-only import of existing agent memories into inbox/")
    im.add_argument("kind", choices=["claude", "codex", "markdown"])
    im.add_argument("path")
    im.add_argument("--scope", default="global", choices=sorted(core.VALID_SCOPES))
    im.add_argument("--project", help="project id (auto-detected from path when scope=project)")
    im.add_argument("--type", default="lesson", choices=sorted(core.VALID_TYPES))
    im.add_argument("--yes", action="store_true", help="actually write (default: dry-run preview)")
    im.set_defaults(func=cmd_import)

    sy = sub.add_parser("sync", help="synchronize the canonical Markdown vault with Git")
    sy_sub = sy.add_subparsers(dest="sync_cmd", required=True)

    sy_init = sy_sub.add_parser("init", help="initialize and configure vault Git sync")
    sy_init.add_argument("url", nargs="?", help="Git remote URL (optional if remote already exists)")
    sy_init.add_argument("--remote", default="origin", help="Git remote name (default: origin)")
    sy_init.add_argument("--branch", default="main", help="remote branch (default: main)")
    sy_init.set_defaults(func=cmd_sync_init)

    sy_status = sy_sub.add_parser("status", help="show local sync state without network access")
    sy_status.set_defaults(func=cmd_sync_status)

    sy_run = sy_sub.add_parser("run", help="commit, pull, push, and rebuild local derived data")
    sy_run.add_argument("--remote", help="override the configured Git remote")
    sy_run.add_argument("--branch", help="override the configured remote branch")
    sy_run.add_argument("--message", help="commit message for local vault changes")
    sy_run.add_argument("--no-push", action="store_true", help="integrate remote changes without pushing")
    sy_run.add_argument(
        "--allow-secrets",
        action="store_true",
        help="bypass the conservative secret scanner (not recommended)",
    )
    sy_run.set_defaults(func=cmd_sync_run)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except ValueError as exc:
        if args.cmd == "serve":
            raise  # never mask server-side errors behind a clean CLI message
        _print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
