"""End-to-end tests for Git-backed vault synchronization."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _run(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _select_home(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setenv("THEATRUM_HOME", str(path))


def _configure_identity(vault: Path) -> None:
    _run(["git", "config", "user.name", "Theatrum Test"], cwd=vault)
    _run(["git", "config", "user.email", "theatrum@example.invalid"], cwd=vault)


def _bare_remote(path: Path) -> None:
    _run(["git", "init", "--bare", str(path)])


def test_two_existing_vaults_merge_and_rebuild_index(tmp_path, monkeypatch):
    from theatrum import core, index, sync

    remote = tmp_path / "vault.git"
    _bare_remote(remote)

    home_a = tmp_path / "a"
    _select_home(monkeypatch, home_a)
    core.init_vault()
    memory_a = core.remember(
        content="# alpha host lesson\nalpha host synchronization detail.",
        type="lesson",
        scope="global",
        source="user_requested",
    )
    sync.initialize(str(remote))
    _configure_identity(core.vault_dir())
    noncanonical = core.global_dir() / "not-a-memory.bin"
    noncanonical.write_bytes(b"local only")
    first = sync.run_sync(message="host a")
    assert first.pushed is True
    tree = _run(["git", "ls-tree", "-r", "main", "--name-only"], cwd=remote)
    assert "global/not-a-memory.bin" not in tree.stdout
    noncanonical.unlink()

    home_b = tmp_path / "b"
    _select_home(monkeypatch, home_b)
    core.init_vault()
    memory_b = core.remember(
        content="# beta host lesson\nbeta host synchronization detail.",
        type="lesson",
        scope="global",
        source="user_requested",
    )
    sync.initialize(str(remote))
    _configure_identity(core.vault_dir())
    second = sync.run_sync(message="host b")
    assert second.pulled is True
    assert second.pushed is True
    assert core.find_memory(memory_a.id) is not None
    assert core.find_memory(memory_b.id) is not None

    # Host A's existing index does not know about host B until sync rebuilds it.
    _select_home(monkeypatch, home_a)
    old_ids = [h.memory.id for h in index.recall("beta host synchronization")]
    assert memory_b.id not in old_ids
    third = sync.run_sync()
    assert third.pulled is True
    assert core.find_memory(memory_b.id) is not None
    assert memory_b.id in [h.memory.id for h in index.recall("beta host synchronization")]
    assert "total active: 2" in core.map_path().read_text(encoding="utf-8")

    ignored = _run(
        ["git", "check-ignore", "MAP.md"],
        cwd=core.vault_dir(),
    )
    assert ignored.stdout.strip() == "MAP.md"
    assert sync.sync_status()["clean"] is True


def test_same_memory_edit_stops_on_conflict(tmp_path, monkeypatch):
    from theatrum import core, sync

    remote = tmp_path / "vault.git"
    _bare_remote(remote)

    home_a = tmp_path / "a"
    _select_home(monkeypatch, home_a)
    core.init_vault()
    memory = core.remember(
        content="# shared lesson\nbase content.",
        type="lesson",
        scope="global",
        source="user_requested",
    )
    sync.initialize(str(remote))
    _configure_identity(core.vault_dir())
    sync.run_sync(message="base")

    home_b = tmp_path / "b"
    _select_home(monkeypatch, home_b)
    core.init_vault()
    sync.initialize(str(remote))
    _configure_identity(core.vault_dir())
    sync.run_sync(message="join host b")
    path_b = core.find_memory(memory.id).path
    path_b.write_text(path_b.read_text(encoding="utf-8") + "host b edit\n", encoding="utf-8")

    _select_home(monkeypatch, home_a)
    path_a = core.find_memory(memory.id).path
    path_a.write_text(path_a.read_text(encoding="utf-8") + "host a edit\n", encoding="utf-8")
    sync.run_sync(message="host a edit")

    _select_home(monkeypatch, home_b)
    with pytest.raises(sync.SyncConflictError, match="sync stopped on Git conflicts"):
        sync.run_sync(message="host b edit")
    status = sync.sync_status()
    assert status["operation"] == "rebase"
    assert status["conflicts"]


def test_secret_scanner_blocks_first_push(tmp_path, monkeypatch):
    from theatrum import core, sync

    remote = tmp_path / "vault.git"
    _bare_remote(remote)
    _select_home(monkeypatch, tmp_path / "host")
    core.init_vault()
    core.remember(
        content='# unsafe\napi_key = "ABCDEFGHIJKLMNOPQRSTUVWX"',
        type="lesson",
        scope="global",
        source="user_requested",
    )
    sync.initialize(str(remote))
    _configure_identity(core.vault_dir())

    with pytest.raises(sync.SyncError, match="possible secrets found"):
        sync.run_sync()
    heads = _run(["git", "for-each-ref", "refs/heads"], cwd=remote)
    assert not heads.stdout.strip()


def test_cli_sync_status_before_init(tmp_path, monkeypatch, capsys):
    from theatrum import cli, core

    _select_home(monkeypatch, tmp_path / "host")
    core.init_vault()
    assert cli.main(["sync", "status"]) == 0
    output = capsys.readouterr().out
    assert '"initialized": false' in output


def test_sync_status_redacts_remote_credentials(tmp_path, monkeypatch):
    from theatrum import core, sync

    _select_home(monkeypatch, tmp_path / "host")
    core.init_vault()
    sync.initialize("https://user:secret@example.com/private/vault.git")
    status = sync.sync_status()
    assert status["remote_url"] == "https://example.com/private/vault.git"
