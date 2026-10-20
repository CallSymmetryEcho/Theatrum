"""
Host wiring (connect/disconnect) and any host-side utilities.

Rules:
- ALWAYS back up the host file before touching it (timestamped copy).
- Never touch any keys other than the ``theatrum`` MCP server entry.
- ``disconnect`` fully reverses ``connect``.
- Claude Code: prefer ``claude mcp add --scope user theatrum -- theatrum serve``
  when the ``claude`` binary is on PATH; else print manual instructions.
- Codex: edit ``~/.codex/config.toml`` [mcp_servers.theatrum] with the resolved
  theatrum command / ``args=["serve"]``. Create the file if absent.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import core


def _theatrum_command() -> str:
    """
    Absolute command hosts should spawn. PATH shim when installed (pipx/uv tool);
    otherwise the currently-running entry point (dev .venv) — hosts don't
    inherit our virtualenv, so a bare "theatrum" would fail to launch.
    """
    return shutil.which("theatrum") or str(Path(sys.argv[0]).resolve())


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
                [binary, "mcp", "add", "--scope", "user", "theatrum", "--", _theatrum_command(), "serve"],
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
# table — the stdlib has no TOML writer, and we're strictly limited to
# ``mcp`` + ``pyyaml``. Never touches other tables/keys.
# Codex rewrites config.toml itself: it adds keys to our table, writes its own
# tables between our begin/end markers, and can drop the begin marker. So the
# markers are decoration only — we remove by table header, never by marker span.
# ponytail: line-based; a line starting with "[" inside a multi-line value in
# our table ends the scan early, and the TOML parse check then refuses the write.
# ---------------------------------------------------------------------------

try:
    import tomllib
except ModuleNotFoundError:  # py3.10
    try:
        import tomli as tomllib  # not a dependency; used only if already present
    except ModuleNotFoundError:
        tomllib = None

_CODEX_CONFIG = Path.home() / ".codex" / "config.toml"

CODEX_BLOCK_TEMPLATE = (
    "\n"
    "# theatrum: begin (do not edit manually — managed by `theatrum connect codex`)\n"
    '[mcp_servers.theatrum]\n'
    'command = "{cmd}"\n'
    'args = ["serve"]\n'
    "# theatrum: end\n"
)

# [mcp_servers.theatrum] or a subtable like [mcp_servers.theatrum.env].
_CODEX_OURS_RE = re.compile(
    r"""^[ \t]*\[[ \t]*mcp_servers[ \t]*\.[ \t]*(?:theatrum|"theatrum"|'theatrum')[ \t]*[\].]""",
    re.MULTILINE,
)
_CODEX_MARKER_RE = re.compile(r"# theatrum: (?:begin\b|end$)")


def _strip_codex_theatrum(text: str) -> str:
    """Drop our table (header, keys, blank lines) and marker comments; keep everything else."""
    out, ours = [], False
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if s.startswith("["):
            ours = bool(_CODEX_OURS_RE.match(line))
        if _CODEX_MARKER_RE.match(s) or (ours and not s.startswith("#")):
            continue
        out.append(line)
    return "".join(out)


def _check_codex_toml(p: Path, new: str) -> None:
    if tomllib is None:
        return
    try:
        tomllib.loads(new)
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(f"refusing to write {p}: result would not be valid TOML ({exc}); file left unchanged")


def _connect_codex() -> str:
    p = _CODEX_CONFIG
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    # Remove any prior theatrum table, then append a fresh one.
    stripped = _strip_codex_theatrum(existing).rstrip() + "\n"
    if stripped.strip() == "":
        stripped = ""
    new = stripped + CODEX_BLOCK_TEMPLATE.format(cmd=_theatrum_command())
    _check_codex_toml(p, new)
    backup = _backup(p)
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
    stripped = _strip_codex_theatrum(existing)
    if stripped == existing:
        return "no theatrum entry in codex config; nothing to do."
    new = stripped.rstrip() + "\n"
    _check_codex_toml(p, new)
    backup = _backup(p)
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


def host_status() -> dict[str, bool | None]:
    """Read-only wiring check. claude_connected is None when the claude CLI is absent/fails."""
    claude: bool | None = None
    binary = _claude_binary()
    if binary:
        try:
            proc = subprocess.run(
                [binary, "mcp", "get", "theatrum"],
                capture_output=True, text=True, timeout=10,
            )
            claude = proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            claude = None
    codex = _CODEX_CONFIG.exists() and bool(_CODEX_OURS_RE.search(_CODEX_CONFIG.read_text(encoding="utf-8")))
    return {"claude_connected": claude, "codex_connected": codex}


def disconnect_host(host: str) -> str:
    if host == "claude":
        return _disconnect_claude()
    if host == "codex":
        return _disconnect_codex()
    raise ValueError(f"unknown host: {host}")
