"""Git-backed synchronization for the canonical Markdown vault.

Only files under ``global/``, ``projects/``, and ``inbox/`` are synchronized.
``MAP.md`` and the SQLite index are derived locally on every host.
"""

from __future__ import annotations

import fcntl
import re
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence
from urllib.parse import urlsplit, urlunsplit

from . import core, importer, index as _index


SYNC_GITIGNORE = """# Theatrum local/generated files (never synchronized)
/MAP.md
/.obsidian/
/.DS_Store
"""
_REMOTE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CREDENTIAL_URL_RE = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@")


class SyncError(ValueError):
    """A synchronization precondition or Git operation failed."""


class SyncConflictError(SyncError):
    """Git stopped because the same canonical file changed on both hosts."""


@dataclass(frozen=True)
class SyncResult:
    remote: str
    branch: str
    committed: bool
    pulled: bool
    pushed: bool
    rebuilt: bool


def _redact_credentials(text: str) -> str:
    return _CREDENTIAL_URL_RE.sub(r"\1***@", text)


def _git(
    args: Sequence[str],
    *,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(core.vault_dir()), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise SyncError("git is required for vault synchronization") from exc
    except subprocess.TimeoutExpired as exc:
        command = _redact_credentials(" ".join(args[:2]))
        raise SyncError(f"git {command} timed out after {timeout}s") from exc
    if check and proc.returncode != 0:
        detail = _redact_credentials((proc.stderr or proc.stdout).strip())
        command = _redact_credentials(" ".join(args))
        raise SyncError(detail or f"git {command} failed")
    return proc


def _validate_remote(remote: str) -> None:
    if not _REMOTE_RE.fullmatch(remote):
        raise SyncError(f"invalid Git remote name: {remote!r}")


def _validate_branch(branch: str) -> None:
    proc = _git(["check-ref-format", "--branch", branch], check=False)
    if proc.returncode != 0:
        raise SyncError(f"invalid Git branch name: {branch!r}")


def _repo_root() -> Path | None:
    proc = _git(["rev-parse", "--show-toplevel"], check=False, timeout=10)
    if proc.returncode != 0:
        return None
    return Path(proc.stdout.strip()).resolve()


def _require_dedicated_repo() -> None:
    root = _repo_root()
    expected = core.vault_dir().resolve()
    if root is None:
        raise SyncError("vault is not a Git repository; run `theatrum sync init` first")
    if root != expected:
        raise SyncError(
            f"vault must be its own Git repository (found parent repository at {root})"
        )


def _ensure_ignore_rule() -> None:
    path = core.vault_dir() / ".gitignore"
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    prefix = current
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    missing = [
        line for line in SYNC_GITIGNORE.splitlines()
        if line and not line.startswith("#") and line not in current.splitlines()
    ]
    if not missing:
        return
    block = "# Theatrum local/generated files (never synchronized)\n"
    core.atomic_write_text(path, prefix + block + "\n".join(missing) + "\n")


def _config_get(key: str) -> str | None:
    proc = _git(["config", "--get", key], check=False, timeout=10)
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def _remote_url(remote: str) -> str | None:
    proc = _git(["remote", "get-url", remote], check=False, timeout=10)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _sanitize_url(url: str | None) -> str | None:
    if not url or "://" not in url:
        return url
    parts = urlsplit(url)
    hostname = parts.hostname or ""
    if parts.port:
        hostname = f"{hostname}:{parts.port}"
    return urlunsplit((parts.scheme, hostname, parts.path, "", ""))


def initialize(
    remote_url: str | None,
    *,
    remote: str = "origin",
    branch: str = "main",
) -> dict[str, object]:
    """Initialize a dedicated vault repository and configure its sync target."""
    _validate_remote(remote)
    core.init_vault()

    root = _repo_root()
    if root is None:
        proc = _git(["init", "-b", branch], check=False, timeout=15)
        if proc.returncode != 0:
            _git(["init"], timeout=15)
            _git(["checkout", "-b", branch], timeout=15)
    else:
        _require_dedicated_repo()

    _validate_branch(branch)
    _ensure_ignore_rule()
    # Older manually initialized vaults may already track the generated map.
    _git(["rm", "--cached", "--ignore-unmatch", "--", "MAP.md"], check=False)

    existing_url = _remote_url(remote)
    if existing_url and remote_url and existing_url != remote_url:
        raise SyncError(
            f"remote {remote!r} already points to {_sanitize_url(existing_url)!r}; "
            "change it explicitly with Git before re-running sync init"
        )
    if not existing_url:
        if not remote_url:
            raise SyncError(
                f"remote {remote!r} is not configured; provide its URL to sync init"
            )
        _git(["remote", "add", remote, remote_url], timeout=15)

    _git(["config", "theatrum.syncRemote", remote], timeout=10)
    _git(["config", "theatrum.syncBranch", branch], timeout=10)
    return sync_status()


def _configured_target(
    remote: str | None,
    branch: str | None,
) -> tuple[str, str]:
    resolved_remote = remote or _config_get("theatrum.syncRemote") or "origin"
    resolved_branch = branch or _config_get("theatrum.syncBranch") or "main"
    _validate_remote(resolved_remote)
    _validate_branch(resolved_branch)
    if not _remote_url(resolved_remote):
        raise SyncError(f"Git remote {resolved_remote!r} is not configured")
    return resolved_remote, resolved_branch


def _nul_paths(proc: subprocess.CompletedProcess[str]) -> list[str]:
    """Decode Git's ``-z`` path output without quotePath escaping.

    Newline-delimited porcelain output quotes non-ASCII and unusual filenames,
    which makes validation operate on Git's display form instead of the real
    path. NUL-delimited output is unquoted and unambiguous.
    """
    return [path for path in proc.stdout.split("\0") if path]


def _conflicted_paths() -> list[str]:
    proc = _git(
        ["diff", "--name-only", "--diff-filter=U", "-z"],
        check=False,
        timeout=10,
    )
    return _nul_paths(proc)


def _operation_in_progress() -> str | None:
    git_dir_proc = _git(["rev-parse", "--git-dir"], check=False, timeout=10)
    if git_dir_proc.returncode != 0:
        return None
    git_dir = Path(git_dir_proc.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = core.vault_dir() / git_dir
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        return "rebase"
    if (git_dir / "MERGE_HEAD").exists():
        return "merge"
    return None


def _canonical_files() -> Iterator[Path]:
    vault = core.vault_dir()
    for dirname in ("global", "projects", "inbox"):
        root = vault / dirname
        if not root.exists():
            continue
        for path in root.rglob("*.md"):
            rel = path.relative_to(vault)
            if any(part.startswith(".") for part in rel.parts):
                continue
            yield path


def _canonical_relpaths() -> list[str]:
    vault = core.vault_dir()
    return sorted(str(path.relative_to(vault)) for path in _canonical_files())


def _is_canonical_relpath(value: str) -> bool:
    path = Path(value)
    if path.suffix != ".md" or not path.parts:
        return False
    if path.parts[0] not in {"global", "projects", "inbox"}:
        return False
    return not any(part.startswith(".") for part in path.parts)


def _tracked_paths() -> list[str]:
    proc = _git(["ls-files", "-z"], check=False, timeout=10)
    return _nul_paths(proc)


def _invalid_tracked_paths() -> list[str]:
    allowed_metadata = {".gitignore"}
    return sorted(
        path for path in _tracked_paths()
        if path not in allowed_metadata and not _is_canonical_relpath(path)
    )


def _secret_paths() -> list[str]:
    vault = core.vault_dir()
    found: list[str] = []
    for path in _canonical_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if importer._has_secret(text):
            found.append(str(path.relative_to(vault)))
    return sorted(found)


@contextmanager
def _sync_lock() -> Iterator[None]:
    core.home().mkdir(parents=True, exist_ok=True)
    lock_path = core.home() / "sync.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SyncError("another Theatrum sync is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _stage_and_commit(message: str | None) -> bool:
    _git(["add", "-A", "--", ".gitignore"])
    current = _canonical_relpaths()
    for start in range(0, len(current), 100):
        _git(["add", "--", *current[start:start + 100]])

    deleted_proc = _git(
        ["ls-files", "--deleted", "-z", "--", "global", "projects", "inbox"],
        check=False,
        timeout=10,
    )
    deleted = [
        path for path in _nul_paths(deleted_proc)
        if _is_canonical_relpath(path)
    ]
    for start in range(0, len(deleted), 100):
        _git(["add", "-u", "--", *deleted[start:start + 100]])

    staged_proc = _git(["diff", "--cached", "--name-only", "-z"], timeout=10)
    invalid_staged = [
        path for path in _nul_paths(staged_proc)
        if path not in {".gitignore", "MAP.md"} and not _is_canonical_relpath(path)
    ]
    if invalid_staged:
        raise SyncError(
            "refusing to commit non-canonical vault paths: " + ", ".join(invalid_staged)
        )
    diff = _git(["diff", "--cached", "--quiet"], check=False, timeout=10)
    if diff.returncode == 0:
        return False
    if diff.returncode != 1:
        raise SyncError((diff.stderr or diff.stdout).strip() or "cannot inspect staged changes")
    commit_message = message or (
        "theatrum sync " + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    _git(["commit", "-m", commit_message], timeout=30)
    return True


def _remote_ref(remote: str, branch: str) -> str:
    return f"refs/remotes/{remote}/{branch}"


def _remote_branch_exists(remote: str, branch: str) -> bool:
    proc = _git(["show-ref", "--verify", "--quiet", _remote_ref(remote, branch)], check=False)
    return proc.returncode == 0


def _histories_related(remote_ref: str) -> bool:
    proc = _git(["merge-base", "HEAD", remote_ref], check=False, timeout=10)
    return proc.returncode == 0


def _integrate(remote: str, branch: str) -> bool:
    _git(["fetch", remote], timeout=60)
    if not _remote_branch_exists(remote, branch):
        return False

    ref = _remote_ref(remote, branch)
    if _histories_related(ref):
        proc = _git(["rebase", ref], check=False, timeout=60)
    else:
        # Joining two pre-existing vaults: unique memory ids merge as a union.
        proc = _git(
            ["merge", "--no-edit", "--allow-unrelated-histories", ref],
            check=False,
            timeout=60,
        )
    if proc.returncode != 0:
        conflicts = _conflicted_paths()
        if conflicts or _operation_in_progress():
            joined = ", ".join(conflicts) if conflicts else "unknown paths"
            raise SyncConflictError(
                f"sync stopped on Git conflicts: {joined}; resolve them in "
                f"{core.vault_dir()} before retrying"
            )
        detail = (proc.stderr or proc.stdout).strip()
        raise SyncError(detail or "cannot integrate remote vault history")
    return True


def run_sync(
    *,
    remote: str | None = None,
    branch: str | None = None,
    message: str | None = None,
    no_push: bool = False,
    allow_secrets: bool = False,
) -> SyncResult:
    """Commit local memories, integrate the remote branch, push, and reindex."""
    _require_dedicated_repo()
    resolved_remote, resolved_branch = _configured_target(remote, branch)

    with _sync_lock():
        operation = _operation_in_progress()
        conflicts = _conflicted_paths()
        if operation or conflicts:
            raise SyncConflictError(
                f"unfinished Git {operation or 'conflict'} in {core.vault_dir()}; "
                "resolve or abort it before syncing"
            )

        if not allow_secrets:
            secret_paths = _secret_paths()
            if secret_paths:
                raise SyncError(
                    "possible secrets found; refusing to sync: " + ", ".join(secret_paths)
                )

        committed = _stage_and_commit(message)
        pulled = _integrate(resolved_remote, resolved_branch)

        # A legacy remote might have tracked the generated map. Convert it to
        # the current canonical-only layout before pushing the merged history.
        _ensure_ignore_rule()
        _git(["rm", "--cached", "--ignore-unmatch", "--", "MAP.md"], check=False)
        invalid_tracked = _invalid_tracked_paths()
        if invalid_tracked:
            raise SyncError(
                "remote tracks non-canonical vault paths; remove them from Git first: "
                + ", ".join(invalid_tracked)
            )
        committed = _stage_and_commit(message) or committed

        post_pull_secrets: list[str] = []
        if not allow_secrets:
            post_pull_secrets = _secret_paths()

        # A successful integration may have changed Markdown even if a later
        # secret check or push fails. Keep local derived data consistent.
        _index.rebuild_index()
        core.write_map()

        if post_pull_secrets:
            raise SyncError(
                "possible secrets found after pull; refusing to push: "
                + ", ".join(post_pull_secrets)
            )

        pushed = False
        if not no_push:
            _git(
                ["push", "--set-upstream", resolved_remote, f"HEAD:{resolved_branch}"],
                timeout=60,
            )
            pushed = True

        return SyncResult(
            remote=resolved_remote,
            branch=resolved_branch,
            committed=committed,
            pulled=pulled,
            pushed=pushed,
            rebuilt=True,
        )


def sync_status() -> dict[str, object]:
    """Return an offline status report without fetching or changing the vault."""
    root = _repo_root()
    if root is None or root != core.vault_dir().resolve():
        return {
            "initialized": False,
            "vault": str(core.vault_dir()),
            "memory_count": sum(1 for _ in core.iter_all_memories()),
        }

    remote = _config_get("theatrum.syncRemote") or "origin"
    branch = _config_get("theatrum.syncBranch") or "main"
    status_proc = _git(["status", "--porcelain=v1"], check=False, timeout=10)
    head_proc = _git(["branch", "--show-current"], check=False, timeout=10)
    conflicts = _conflicted_paths()
    report: dict[str, object] = {
        "initialized": True,
        "vault": str(core.vault_dir()),
        "remote": remote,
        "remote_url": _sanitize_url(_remote_url(remote)),
        "branch": branch,
        "current_branch": head_proc.stdout.strip() or None,
        "clean": not bool(status_proc.stdout.strip()),
        "operation": _operation_in_progress(),
        "conflicts": conflicts,
        "invalid_tracked_paths": _invalid_tracked_paths(),
        "memory_count": sum(1 for _ in core.iter_all_memories()),
    }
    ref = _remote_ref(remote, branch)
    if _remote_branch_exists(remote, branch):
        counts = _git(
            ["rev-list", "--left-right", "--count", f"HEAD...{ref}"],
            check=False,
            timeout=10,
        )
        if counts.returncode == 0:
            left, right = counts.stdout.split()
            report["ahead"] = int(left)
            report["behind"] = int(right)
    return report
