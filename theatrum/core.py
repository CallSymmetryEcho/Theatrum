"""
Theatrum core: vault I/O, frontmatter, IDs, project identity, capture, feedback,
MAP.md, and health checks.

Markdown files are the source of truth. The disposable SQLite/FTS index lives in
``theatrum.index`` and is rebuilt silently when missing or schema-stale.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_TYPES = {
    "preference", "decision", "lesson", "solution", "synthesis", "project-summary",
}
VALID_SCOPES = {"global", "project"}
VALID_STATUSES = {"active", "proposed", "superseded"}
VALID_SOURCES = {"user_requested", "agent_inferred"}
VALID_CONFIDENCE = {"low", "medium", "high"}
CONFIDENCE_TO_FLOAT = {"low": 0.0, "medium": 0.5, "high": 1.0}
VALID_OUTCOMES = {"useful", "dead_end"}


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def home() -> Path:
    """Root Theatrum directory. Honors ``THEATRUM_HOME`` for test isolation."""
    env = os.environ.get("THEATRUM_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".theatrum").resolve()


def vault_dir() -> Path:
    return home() / "vault"


def global_dir() -> Path:
    return vault_dir() / "global"


def projects_dir() -> Path:
    return vault_dir() / "projects"


def inbox_dir() -> Path:
    return vault_dir() / "inbox"


def map_path() -> Path:
    return vault_dir() / "MAP.md"


def index_path() -> Path:
    return home() / "index.db"


def projects_registry_path() -> Path:
    return home() / "projects.json"


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------

def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically via same-dir tempfile + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Frontmatter parse / dump
# ---------------------------------------------------------------------------

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body_string). Missing frontmatter => ({}, text)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw, body = m.group(1), m.group(2)
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data, body


def dump_frontmatter(meta: dict[str, Any], body: str) -> str:
    """Serialize frontmatter + body back to a memory file string."""
    order = [
        "id", "type", "scope", "project", "tags", "created", "source",
        "status", "confidence", "derived_from", "superseded_by", "used", "dead_end",
    ]
    ordered: dict[str, Any] = {}
    for k in order:
        if k in meta:
            ordered[k] = meta[k]
    for k, v in meta.items():
        if k not in ordered:
            ordered[k] = v
    fm = yaml.safe_dump(
        ordered, sort_keys=False, allow_unicode=True, default_flow_style=False,
    ).rstrip("\n")
    body = body if body.endswith("\n") else body + "\n"
    if not body.startswith("\n"):
        body = "\n" + body
    return f"---\n{fm}\n---{body}"


# ---------------------------------------------------------------------------
# IDs
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_UNICODE_SLUG_RE = re.compile(r"[^\w]+", re.UNICODE)


def _slug(text: str, max_len: int = 40) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower().strip()
    ascii_text = _SLUG_RE.sub("-", ascii_text).strip("-")
    if ascii_text:
        return ascii_text[:max_len].rstrip("-") or uuid.uuid4().hex[:8]
    # Fallback for non-ASCII titles (e.g. CJK): unicode-aware pass on the original.
    uni = _UNICODE_SLUG_RE.sub("-", text.lower()).strip("-")
    if uni:
        return uni[:max_len].rstrip("-") or uuid.uuid4().hex[:8]
    return uuid.uuid4().hex[:8]


def make_id(title_hint: str, when: date | None = None) -> str:
    when = when or datetime.now(timezone.utc).date()
    return f"{when.strftime('%Y%m%d')}-{_slug(title_hint)}"


def _claim_id(base_id: str, dest_dir: Path) -> str:
    """
    Atomically claim an id by exclusively creating the file in ``dest_dir``.
    Returns the id that was successfully claimed (base_id or base_id-2, -3, …).
    Raises FileExistsError only after an unreasonable number of retries.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    candidate = base_id
    n = 2
    while True:
        path = dest_dir / f"{candidate}.md"
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return candidate
        except FileExistsError:
            candidate = f"{base_id}-{n}"
            n += 1
            if n > 9999:
                raise


def _unique_id(base_id: str, dest_dir: Path | None = None) -> str:
    """
    Return a unique memory id. When ``dest_dir`` is provided, atomically
    claims the file slot (O_CREAT|O_EXCL) — no O(N) vault scan.
    Legacy fallback (``dest_dir=None``) retains the scan-then-check path for
    callers that don't know the destination yet (should not happen in normal flow).
    """
    if dest_dir is not None:
        return _claim_id(base_id, dest_dir)
    # Legacy path: scan vault (kept for backward compatibility only)
    def exists(mid: str) -> bool:
        for m in iter_all_memories():
            if m.id == mid:
                return True
        return False
    if not exists(base_id):
        return base_id
    n = 2
    while True:
        candidate = f"{base_id}-{n}"
        if not exists(candidate):
            return candidate
        n += 1


# ---------------------------------------------------------------------------
# Project identity
#   Prefer normalized git remote of cwd → fall back to path→id registry.
#   No fuzzy matching: a wrong project match is worse than no match.
# ---------------------------------------------------------------------------

_GIT_URL_RE = re.compile(
    r"""
    ^\s*
    (?:(?:https?|git|ssh)://)?     # optional protocol
    (?:[^@\s]+@)?                  # optional user@ (credentials)
    ([^:/\s]+)                     # host
    [:/]+                          # separator (: for ssh scp-form, / otherwise)
    (.+?)                          # path
    (?:\.git)?                     # optional .git suffix
    /?\s*$
    """,
    re.VERBOSE,
)


def normalize_git_remote(url: str) -> str | None:
    """
    Normalize a git remote URL to ``host/path`` form: lowercase host, no
    protocol, no credentials, no ``.git`` suffix, no trailing slash. Returns
    None if the URL can't be parsed.
    """
    if not url:
        return None
    m = _GIT_URL_RE.match(url.strip())
    if not m:
        return None
    host = m.group(1).lower()
    path = m.group(2).strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not path:
        return None
    return f"{host}/{path}"


def _git_remote_for(cwd: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return normalize_git_remote(proc.stdout.strip())


def _load_registry() -> dict[str, str]:
    p = projects_registry_path()
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_registry(reg: dict[str, str]) -> None:
    atomic_write_json(projects_registry_path(), reg)


def detect_project(cwd: Path | None = None) -> str:
    """
    Return the project id for ``cwd`` (default: ``os.getcwd()``).

    Priority: normalized git remote > registry entry > auto-register
    ``<basename>-<8-char-hash-of-abspath>``.
    """
    cwd = (cwd or Path(os.getcwd())).resolve()
    remote = _git_remote_for(cwd)
    if remote:
        return remote
    reg = _load_registry()
    key = str(cwd)
    if key in reg:
        return reg[key]
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    pid = f"{_slug(cwd.name)}-{digest}"
    reg[key] = pid
    _save_registry(reg)
    return pid


def register_project(cwd: Path, project_id: str) -> None:
    _validate_project_id(project_id)
    reg = _load_registry()
    reg[str(cwd.resolve())] = project_id
    _save_registry(reg)


# ---------------------------------------------------------------------------
# Vault init
# ---------------------------------------------------------------------------

DEFAULT_MAP = """# Theatrum Vault

Auto-maintained overview. Do not edit by hand — regenerated on every write.
"""


def init_vault() -> Path:
    """Create the vault skeleton if it does not exist. Idempotent."""
    v = vault_dir()
    global_dir().mkdir(parents=True, exist_ok=True)
    projects_dir().mkdir(parents=True, exist_ok=True)
    inbox_dir().mkdir(parents=True, exist_ok=True)
    if not map_path().exists():
        atomic_write_text(map_path(), DEFAULT_MAP)
    if not projects_registry_path().exists():
        atomic_write_json(projects_registry_path(), {})
    return v


# ---------------------------------------------------------------------------
# Memory data model
# ---------------------------------------------------------------------------

@dataclass
class Memory:
    id: str
    type: str
    scope: str
    project: str | None
    tags: list[str]
    created: str          # ISO date (YYYY-MM-DD)
    source: str
    status: str
    confidence: str
    derived_from: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    used: int = 0
    dead_end: int = 0
    title_hint: str | None = None   # explicit title from frontmatter, if any
    body: str = ""
    path: Path | None = None

    def title(self) -> str:
        if self.title_hint:
            return self.title_hint
        for line in self.body.splitlines():
            s = line.strip()
            if s.startswith("#"):
                return s.lstrip("#").strip()
            if s:
                return s[:80]
        return self.id

    def to_meta(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title_hint,
            "type": self.type,
            "scope": self.scope,
            "project": self.project,
            "tags": list(self.tags),
            "created": self.created,
            "source": self.source,
            "status": self.status,
            "confidence": self.confidence,
            "derived_from": list(self.derived_from),
            "superseded_by": self.superseded_by,
            "used": int(self.used),
            "dead_end": int(self.dead_end),
        }

    def render(self) -> str:
        return dump_frontmatter(self.to_meta(), self.body)


# ---------------------------------------------------------------------------
# Vault I/O
# ---------------------------------------------------------------------------

def _validate_project_id(project: str) -> None:
    """
    Reject project ids that could escape the projects directory:
    - empty string
    - absolute paths
    - backslash anywhere
    - any ".." path segment
    - resolved path not inside projects_dir()
    Raises ValueError with a descriptive message.
    """
    if not project:
        raise ValueError("project id must not be empty")
    if os.path.isabs(project):
        raise ValueError(f"project id must not be an absolute path: {project!r}")
    if "\\" in project:
        raise ValueError(f"project id must not contain backslashes: {project!r}")
    parts = Path(project).parts
    if ".." in parts:
        raise ValueError(f"project id must not contain '..' segments: {project!r}")
    resolved = (projects_dir() / project).resolve()
    base = projects_dir().resolve()
    if not resolved.is_relative_to(base):
        raise ValueError(
            f"project id {project!r} resolves outside projects directory"
        )


def _memory_dir(scope: str, project: str | None, status: str) -> Path:
    """
    Where the file lives on disk.

    - ``status == "proposed"``  → ``inbox/``
    - ``scope == "global"``     → ``global/``
    - ``scope == "project"``    → ``projects/<project-id>/``
    """
    if status == "proposed":
        return inbox_dir()
    if scope == "global":
        return global_dir()
    if scope == "project":
        if not project:
            raise ValueError("project scope requires a project id")
        _validate_project_id(project)
        return projects_dir() / project
    raise ValueError(f"unknown scope: {scope}")


def write_memory(mem: Memory) -> Path:
    """Persist ``mem`` and update its ``path`` field. Atomic."""
    d = _memory_dir(mem.scope, mem.project, mem.status)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{mem.id}.md"
    atomic_write_text(p, mem.render())
    mem.path = p
    return p


def read_memory(path: Path) -> Memory | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = parse_frontmatter(text)
    if not meta or "id" not in meta:
        return None
    created = meta.get("created")
    if isinstance(created, (date, datetime)):
        created_str = created.isoformat() if isinstance(created, date) else created.date().isoformat()
    else:
        created_str = str(created) if created else datetime.now(timezone.utc).date().isoformat()
    tags = meta.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]
    derived = meta.get("derived_from") or []
    if not isinstance(derived, list):
        derived = [str(derived)]
    return Memory(
        id=str(meta["id"]),
        type=str(meta.get("type", "lesson")),
        scope=str(meta.get("scope", "global")),
        project=(str(meta["project"]) if meta.get("project") else None),
        tags=[str(t) for t in tags],
        created=created_str,
        source=str(meta.get("source", "user_requested")),
        status=str(meta.get("status", "active")),
        confidence=str(meta.get("confidence", "medium")),
        derived_from=[str(d) for d in derived],
        superseded_by=(str(meta["superseded_by"]) if meta.get("superseded_by") else None),
        used=int(meta.get("used", 0) or 0),
        dead_end=int(meta.get("dead_end", 0) or 0),
        title_hint=(str(meta["title"]) if meta.get("title") else None),
        body=body,
        path=path,
    )


def iter_all_memories() -> Iterable[Memory]:
    v = vault_dir()
    if not v.exists():
        return
    for p in v.rglob("*.md"):
        if p.name == "MAP.md":
            continue
        # Skip any file whose relative path has a component starting with "."
        # (guards against .obsidian/, .git/, or other hidden dirs inside the vault).
        rel = p.relative_to(v)
        if any(part.startswith(".") for part in rel.parts):
            continue
        m = read_memory(p)
        if m is not None:
            yield m


def find_memory(mem_id: str) -> Memory | None:
    for m in iter_all_memories():
        if m.id == mem_id:
            return m
    return None


# ---------------------------------------------------------------------------
# Remember (high-level capture)
# ---------------------------------------------------------------------------

def _first_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:60]
    return ""


def remember(
    *,
    content: str,
    type: str,
    scope: str,
    project: str | None = None,
    tags: Sequence[str] = (),
    source: str,
    derived_from: Sequence[str] = (),
    confidence: str = "medium",
    title_hint: str | None = None,
) -> Memory:
    """
    Create and persist a memory. Returns the saved Memory (with ``.path`` set).

    ``source == "agent_inferred"`` lands in inbox/ with ``status: proposed``;
    ``user_requested`` is ``active`` immediately.
    """
    from . import index as _index

    if type not in VALID_TYPES:
        raise ValueError(f"invalid type: {type}")
    if scope not in VALID_SCOPES:
        raise ValueError(f"invalid scope: {scope}")
    if source not in VALID_SOURCES:
        raise ValueError(f"invalid source: {source}")
    if confidence not in VALID_CONFIDENCE:
        raise ValueError(f"invalid confidence: {confidence}")
    if scope == "project":
        if not project:
            raise ValueError("project scope requires --project")
        # Validate up front, even for inbox-bound (proposed) memories:
        # _memory_dir skips project validation when status == "proposed",
        # and a hostile project id must never be planted in the vault.
        _validate_project_id(project)

    status = "proposed" if source == "agent_inferred" else "active"
    hint = title_hint or _first_line(content) or type
    # Determine dest_dir up front so we can atomically claim the id there.
    dest_dir = _memory_dir(scope, project if scope == "project" else None, status)
    dest_dir.mkdir(parents=True, exist_ok=True)
    mem_id = _unique_id(make_id(hint), dest_dir=dest_dir)

    mem = Memory(
        id=mem_id,
        type=type,
        scope=scope,
        project=(project if scope == "project" else None),
        tags=list(tags),
        created=datetime.now(timezone.utc).date().isoformat(),
        source=source,
        status=status,
        confidence=confidence,
        derived_from=list(derived_from),
        superseded_by=None,
        used=0,
        dead_end=0,
        title_hint=title_hint,  # only explicit titles are persisted
        body=content if content.endswith("\n") else content + "\n",
    )
    write_memory(mem)
    _index.ensure_index()
    _index.index_upsert(mem)
    write_map()
    return mem


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

def apply_feedback(ids: Sequence[str], outcome: str) -> list[Memory]:
    """
    Increment ``used``/``dead_end`` on each memory. Re-persists frontmatter
    atomically and reindexes so ranking updates.
    """
    from . import index as _index

    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"invalid outcome: {outcome}")
    updated: list[Memory] = []
    for mem_id in ids:
        mem = find_memory(mem_id)
        if mem is None:
            continue
        if outcome == "useful":
            mem.used += 1
        else:
            mem.dead_end += 1
        write_memory(mem)
        _index.index_upsert(mem)
        updated.append(mem)
    if updated:
        write_map()
    return updated


# ---------------------------------------------------------------------------
# Curation: approve (inbox → active) and forget (delete)
# ---------------------------------------------------------------------------

def approve(ids: Sequence[str]) -> list[Memory]:
    """Promote proposed (inbox) memories to active. Moves the file out of inbox/."""
    from . import index as _index

    approved: list[Memory] = []
    for mem_id in ids:
        mem = find_memory(mem_id)
        if mem is None or mem.status != "proposed":
            continue
        old_path = mem.path
        mem.status = "active"
        try:
            write_memory(mem)  # routes by status → scope dir; updates mem.path
        except ValueError:
            # Hand-edited/hostile frontmatter (e.g. bad project id) must not
            # crash the batch — skip this one, keep approving the rest.
            mem.status = "proposed"
            continue
        if old_path is not None and old_path != mem.path:
            old_path.unlink(missing_ok=True)
        _index.ensure_index()
        _index.index_upsert(mem)
        approved.append(mem)
    if approved:
        write_map()
    return approved


def forget(ids: Sequence[str]) -> list[str]:
    """Delete memories permanently: file + index row. Git is the recovery path."""
    from . import index as _index

    removed: list[str] = []
    for mem_id in ids:
        mem = find_memory(mem_id)
        if mem is None:
            continue
        if mem.path is not None:
            mem.path.unlink(missing_ok=True)
        _index.ensure_index()
        _index.index_delete(mem.id)
        removed.append(mem.id)
    if removed:
        write_map()
    return removed


# ---------------------------------------------------------------------------
# MAP.md — dumb deterministic regeneration, no LLM, ever
# ---------------------------------------------------------------------------

def write_map() -> Path:
    # ponytail: O(N) vault scan per write, incremental MAP if vaults grow past ~5k memories
    mems = list(iter_all_memories())
    active = [m for m in mems if m.status == "active"]

    per_project: dict[str, int] = {}
    for m in active:
        if m.scope == "project" and m.project:
            per_project[m.project] = per_project.get(m.project, 0) + 1
    global_count = sum(1 for m in active if m.scope == "global")
    inbox_count = sum(1 for m in mems if m.status == "proposed")

    tag_counts: dict[str, int] = {}
    for m in active:
        for t in m.tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    recent = sorted(active, key=lambda m: m.created, reverse=True)[:5]

    lines = [
        "# Theatrum Vault", "",
        "Auto-maintained overview. Do not edit by hand — regenerated on every write.",
        "", "## Counts", "",
        f"- global: {global_count}",
        f"- projects: {len(per_project)}",
        f"- inbox (proposed): {inbox_count}",
        f"- total active: {len(active)}",
        "", "## Projects", "",
    ]
    if per_project:
        for pid, n in sorted(per_project.items()):
            lines.append(f"- `{pid}` — {n}")
    else:
        lines.append("_none yet_")
    lines += ["", "## Top tags", ""]
    if top_tags:
        for tag, n in top_tags:
            lines.append(f"- `{tag}` × {n}")
    else:
        lines.append("_none yet_")
    lines += ["", "## Recent", ""]
    if recent:
        for m in recent:
            lines.append(f"- {m.created} — `{m.id}` — {m.title()}")
    else:
        lines.append("_none yet_")
    lines.append("")

    atomic_write_text(map_path(), "\n".join(lines))
    return map_path()


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------

def doctor() -> dict[str, Any]:
    """Minimal health report: vault exists, index openable/rebuildable, counts."""
    from . import index as _index

    report: dict[str, Any] = {
        "theatrum_home": str(home()),
        "vault_exists": vault_dir().exists(),
        "map_exists": map_path().exists(),
        "index_path": str(index_path()),
    }
    try:
        _index.ensure_index()
        report["index_ok"] = True
    except Exception as exc:  # noqa: BLE001 - doctor reports, never crashes
        report["index_ok"] = False
        report["index_error"] = repr(exc)

    total = active = proposed = 0
    projects: set[str] = set()
    for m in iter_all_memories():
        total += 1
        if m.status == "active":
            active += 1
        if m.status == "proposed":
            proposed += 1
        if m.scope == "project" and m.project:
            projects.add(m.project)
    report.update(
        total_memories=total,
        active_memories=active,
        proposed_memories=proposed,
        project_count=len(projects),
    )
    return report
