"""
Host wiring (connect/disconnect) and any host-side utilities.

Rules:
- ALWAYS back up the host file before touching it (timestamped copy).
- Never touch any keys other than the ``theatrum`` MCP server entry.
- ``disconnect`` fully reverses ``connect``.
- Claude Code: prefer ``claude mcp add --scope user theatrum -- theatrum serve``
  when the ``claude`` binary is on PATH; else print manual instructions.
- Codex: edit ``~/.codex/config.toml`` [mcp_servers.theatrum] with
  ``command="theatrum"`` / ``args=["serve"]``. Create the file if absent.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import core


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------

def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(path.name + f".bak-{stamp}")
    n = 1
    while dest.exists():  # same-second collision must not overwrite an earlier backup
        dest = path.with_name(path.name + f".bak-{stamp}.{n}")
        n += 1
    shutil.copy2(path, dest)
    return dest


# ---------------------------------------------------------------------------
# Claude Code
# ---------------------------------------------------------------------------

def _claude_binary() -> str | None:
    return shutil.which("claude")


def _connect_claude() -> str:
    binary = _claude_binary()
    if binary:
        # ``claude`` manages its own config; it can write to the correct scope
        # atomically. We still record a manual-fallback backup of the settings
        # file if we can find it.
        settings = _claude_settings_path()
        backup = _backup(settings) if settings else None
        try:
            proc = subprocess.run(
                [binary, "mcp", "add", "--scope", "user", "theatrum", "--", "theatrum", "serve"],
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"failed to run claude CLI: {exc!r}\n" + _claude_manual_instructions()
        if proc.returncode != 0:
            return (
                f"claude mcp add failed (exit {proc.returncode}):\n"
                f"stdout: {proc.stdout}\nstderr: {proc.stderr}\n"
                + _claude_manual_instructions()
            )
        msg = "connected: claude (via `claude mcp add --scope user`)"
        if backup:
            msg += f"\nbackup: {backup}"
        return msg
    return "claude binary not found on PATH.\n" + _claude_manual_instructions()


def _disconnect_claude() -> str:
    binary = _claude_binary()
    if binary:
        settings = _claude_settings_path()
        backup = _backup(settings) if settings else None
        try:
            proc = subprocess.run(
                [binary, "mcp", "remove", "--scope", "user", "theatrum"],
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"failed to run claude CLI: {exc!r}"
        if proc.returncode != 0:
            return (
                f"claude mcp remove failed (exit {proc.returncode}):\n"
                f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
            )
        msg = "disconnected: claude"
        if backup:
            msg += f"\nbackup: {backup}"
        return msg
    return "claude binary not found on PATH; nothing to disconnect."


def _claude_settings_path() -> Path | None:
    candidates = [
        Path.home() / ".claude" / "settings.json",
        Path.home() / ".config" / "claude" / "settings.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _claude_manual_instructions() -> str:
    return (
        "manual setup:\n"
        "  1. install the theatrum CLI so `theatrum serve` is on PATH\n"
        "  2. run: claude mcp add --scope user theatrum -- theatrum serve\n"
        "     (or add an MCP server entry named 'theatrum' with command='theatrum', args=['serve'])"
    )


# ---------------------------------------------------------------------------
# Codex (edit ~/.codex/config.toml)
#
# We use a tiny hand-rolled TOML patcher for the single [mcp_servers.theatrum]
# section — the stdlib has no TOML writer, and we're strictly limited to
# ``mcp`` + ``pyyaml``. Never touches other sections/keys.
# ponytail: this is only safe because we own exactly one section. If Codex ever
# adds more theatrum-managed keys, replace this with a proper TOML round-trip.
# ---------------------------------------------------------------------------

_CODEX_CONFIG = Path.home() / ".codex" / "config.toml"

CODEX_BLOCK = (
    "\n"
    "# theatrum: begin (do not edit manually — managed by `theatrum connect codex`)\n"
    '[mcp_servers.theatrum]\n'
    'command = "theatrum"\n'
    'args = ["serve"]\n'
    "# theatrum: end\n"
)

_CODEX_BLOCK_RE = re.compile(
    r"\n?^# theatrum: begin\b[^\n]*$.*?^# theatrum: end$\n?",
    re.DOTALL | re.MULTILINE,
)


def _connect_codex() -> str:
    p = _CODEX_CONFIG
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    backup = _backup(p)
    # Remove any prior theatrum block, then append a fresh one.
    stripped = _CODEX_BLOCK_RE.sub("\n", existing).rstrip() + "\n"
    if stripped.strip() == "":
        stripped = ""
    new = stripped + CODEX_BLOCK
    core.atomic_write_text(p, new)
    msg = f"connected: codex → {p}"
    if backup:
        msg += f"\nbackup: {backup}"
    return msg


def _disconnect_codex() -> str:
    p = _CODEX_CONFIG
    if not p.exists():
        return "codex config not found; nothing to disconnect."
    existing = p.read_text(encoding="utf-8")
    if "# theatrum: begin" not in existing:
        return "no theatrum block in codex config; nothing to do."
    backup = _backup(p)
    new = _CODEX_BLOCK_RE.sub("\n", existing).rstrip() + "\n"
    core.atomic_write_text(p, new)
    msg = f"disconnected: codex → {p}"
    if backup:
        msg += f"\nbackup: {backup}"
    return msg


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def connect_host(host: str) -> str:
    if host == "claude":
        return _connect_claude()
    if host == "codex":
        return _connect_codex()
    raise ValueError(f"unknown host: {host}")


def disconnect_host(host: str) -> str:
    if host == "claude":
        return _disconnect_claude()
    if host == "codex":
        return _disconnect_codex()
    raise ValueError(f"unknown host: {host}")
