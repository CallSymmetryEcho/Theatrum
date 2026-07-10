"""Read-only importers: existing agent memories → inbox/ (proposed, human-reviewed)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from . import core


# ---------------------------------------------------------------------------
# Secret filter — trust boundary. Any match => skip the whole file.
# ---------------------------------------------------------------------------

_SECRET_RES = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                      # AWS access key
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),                   # GitHub PAT
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),                 # OpenAI/Anthropic-style
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),          # Slack
    re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[=:]\s*['\"]?[A-Za-z0-9_\-/+]{16,}"),
]


def _has_secret(text: str) -> bool:
    return any(rx.search(text) for rx in _SECRET_RES)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Candidate collection — read-only, deterministic, no writes to source paths.
# ---------------------------------------------------------------------------

def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("#").strip() or None
    return None


def _has_hidden_component(rel: Path) -> bool:
    return any(part.startswith(".") for part in rel.parts)


def collect(kind: str, path: Path) -> list[tuple[Path, str, str]]:
    """Return `(source_file, title, body)` candidates. Never writes."""
    if kind == "claude":
        if not path.is_dir():
            raise ValueError(f"claude import expects a directory: {path}")
        out: list[tuple[Path, str, str]] = []
        for f in path.rglob("*.md"):
            if f.name == "MEMORY.md":
                continue
            rel = f.relative_to(path)
            if _has_hidden_component(rel):
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = core.parse_frontmatter(text)
            title = str(meta.get("description") or meta.get("name") or f.stem)
            if not body.strip():
                continue
            out.append((f, title, body))
        out.sort(key=lambda t: str(t[0]))
        return out

    if kind == "codex":
        if path.is_dir():
            file = path / "AGENTS.md"
        else:
            file = path
        if not file.is_file():
            raise ValueError(f"codex import: AGENTS.md not found at {file}")
        try:
            text = file.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"codex import: cannot read {file}: {exc}") from exc
        if not text.strip():
            return []
        title = _first_heading(text) or f"Codex guidance — {file.parent.name}"
        return [(file, title, text)]

    if kind == "markdown":
        candidates: list[tuple[Path, str, str]] = []
        if path.is_file():
            files = [path]
            base = path.parent
        elif path.is_dir():
            files = [
                f for f in path.rglob("*.md")
                if not _has_hidden_component(f.relative_to(path))
            ]
            base = path
        else:
            raise ValueError(f"markdown import: path not found: {path}")
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = core.parse_frontmatter(text)
            title = str(meta.get("title") or _first_heading(body) or f.stem)
            if not body.strip():
                continue
            candidates.append((f, title, body))
        candidates.sort(key=lambda t: str(t[0]))
        return candidates

    raise ValueError(f"unknown import kind: {kind}")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_import(
    kind: str,
    path: Path,
    *,
    scope: str,
    project: str | None,
    type: str,
    yes: bool,
) -> dict[str, Any]:
    """Collect → filter (secrets, dupes) → optionally write to inbox/ as proposed."""
    candidates = collect(kind, path)

    # Dedupe against already-imported memories + against files earlier in this batch.
    # ponytail: remember() regenerates MAP.md per memory — O(N²) at vault scale is fine.
    existing_hashes = {
        m.import_hash for m in core.iter_all_memories() if m.import_hash
    }
    batch_hashes: set[str] = set()

    imported: list[tuple[str, str]] = []
    duplicates: list[str] = []
    secrets: list[str] = []

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(path if path.is_dir() else path.parent))
        except ValueError:
            return str(p)

    for source_file, title, body in candidates:
        rel = _rel(source_file)
        if _has_secret(body) or _has_secret(title):
            secrets.append(rel)
            continue
        h = _content_hash(body)
        if h in existing_hashes or h in batch_hashes:
            duplicates.append(rel)
            continue
        if yes:
            mem = core.remember(
                content=body,
                type=type,
                scope=scope,
                project=project,
                tags=[],
                source="imported",
                title_hint=title,
                import_path=str(source_file.resolve()),
                import_hash=h,
            )
            imported.append((mem.id, rel))
            batch_hashes.add(h)
        else:
            imported.append((title, rel))
            batch_hashes.add(h)

    return {"imported": imported, "duplicates": duplicates, "secrets": secrets}
