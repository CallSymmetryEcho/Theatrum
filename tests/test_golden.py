"""
Golden scenarios (§1 of V1_MASTER_PLAN.md) as tests against an isolated
temporary ``$HOME`` via ``THEATRUM_HOME``. Also covers proposed-memory
exclusion, feedback reranking, index rebuild, and ranking floors.
"""

from __future__ import annotations

import os
from importlib import reload
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own THEATRUM_HOME. Modules are reloaded so any
    module-level constants derived from Path.home() (e.g. Codex config path)
    are rebuilt against the sandboxed HOME."""
    monkeypatch.setenv("THEATRUM_HOME", str(tmp_path / "theatrum"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    # Reload so any Path.home() captured at import time picks up the new HOME.
    import theatrum.core as core_mod
    reload(core_mod)
    import theatrum.index as index_mod
    reload(index_mod)
    import theatrum.connect as connect_mod
    reload(connect_mod)
    yield


def _mods():
    import theatrum.core as core_mod
    import theatrum.index as index_mod
    return core_mod, index_mod


# ---------------------------------------------------------------------------
# Golden scenario 1: same project cross-agent recall
# ---------------------------------------------------------------------------

def test_scenario_1_same_project_cross_agent_recall():
    core, idx = _mods()
    core.init_vault()

    # Agent A on project X saves a decision.
    mem = core.remember(
        content="# use trigram tokenizer\nFTS5 trigram works for CJK. Chose it over jieba.",
        type="decision",
        scope="project",
        project="github.com/acme/x",
        tags=["sqlite", "fts5"],
        source="user_requested",
    )
    assert mem.status == "active"
    assert mem.path is not None and mem.path.exists()

    # Agent B (same project, different session) recalls it.
    hits = idx.recall("trigram tokenizer", project="github.com/acme/x")
    assert mem.id in [h.memory.id for h in hits]


# ---------------------------------------------------------------------------
# Golden scenario 2: global preference visible from multiple projects
# ---------------------------------------------------------------------------

def test_scenario_2_global_preference_visible_from_two_projects():
    core, idx = _mods()
    core.init_vault()

    core.remember(
        content="# concise commit style\nprefer imperative one-line commit subjects.",
        type="preference",
        scope="global",
        tags=["git"],
        source="user_requested",
    )

    hits_x = idx.recall("commit style", project="github.com/acme/x")
    hits_y = idx.recall("commit style", project="github.com/acme/y")

    assert any(h.memory.scope == "global" for h in hits_x)
    assert any(h.memory.scope == "global" for h in hits_y)


# ---------------------------------------------------------------------------
# Golden scenario 3: project X memory NEVER leaks to project Y
# ---------------------------------------------------------------------------

def test_scenario_3_project_isolation_is_hard_filter():
    core, idx = _mods()
    core.init_vault()

    core.remember(
        content="# secret project X detail\nInternal codename banana codename detail.",
        type="lesson",
        scope="project",
        project="github.com/acme/x",
        tags=["internal"],
        source="user_requested",
    )

    hits = idx.recall("banana codename detail", project="github.com/acme/y")
    for h in hits:
        assert not (h.memory.scope == "project" and h.memory.project == "github.com/acme/x"), \
            "project X memory leaked into project Y recall"


# ---------------------------------------------------------------------------
# Golden scenario 4: flywheel — deep context + synthesis with derived_from
# ---------------------------------------------------------------------------

def test_scenario_4_flywheel_synthesis_with_derived_from():
    core, idx = _mods()
    core.init_vault()

    project = "github.com/acme/x"

    a = core.remember(
        content="# lesson: retry needs jitter\nplain exponential backoff retry caused thundering herd.",
        type="lesson", scope="project", project=project,
        tags=["retry"], source="user_requested",
    )
    b = core.remember(
        content="# lesson: cap max retry attempts\nunbounded retry masked real failures for 20 minutes.",
        type="lesson", scope="project", project=project,
        tags=["retry"], source="user_requested",
    )

    # Deep context should include both lessons.
    ctx = idx.build_context("retry backoff jitter", budget=4000, deep=True, project=project)
    assert a.id in ctx
    assert b.id in ctx

    # Synthesize with derived_from provenance.
    synth = core.remember(
        content="# synthesis: retry policy\nuse capped exponential backoff retry with jitter.",
        type="synthesis", scope="project", project=project,
        tags=["retry"], source="user_requested",
        derived_from=[a.id, b.id],
    )
    text = synth.path.read_text(encoding="utf-8")
    assert a.id in text and b.id in text, "derived_from links missing from synthesis file"

    hits = idx.recall("retry policy synthesis backoff", project=project)
    assert synth.id in [h.memory.id for h in hits]


# ---------------------------------------------------------------------------
# agent_inferred → inbox proposed, excluded from recall/context
# ---------------------------------------------------------------------------

def test_agent_inferred_goes_to_inbox_and_is_excluded():
    core, idx = _mods()
    core.init_vault()

    mem = core.remember(
        content="# proposed lesson\nagent guessed this proposed lesson pattern is useful.",
        type="lesson", scope="global",
        source="agent_inferred",
    )
    assert mem.status == "proposed"
    assert core.inbox_dir() in mem.path.parents

    hits = idx.recall("proposed lesson pattern")
    assert mem.id not in [h.memory.id for h in hits], \
        "proposed memories must be excluded from recall"

    ctx = idx.build_context("proposed lesson pattern", budget=4000)
    assert mem.id not in ctx


# ---------------------------------------------------------------------------
# Feedback increments counters and moves ranking
# ---------------------------------------------------------------------------

def test_feedback_reranks_by_usefulness():
    core, idx = _mods()
    core.init_vault()

    project = "p"
    a = core.remember(
        content="# alpha strategy\nkeyword alpha strategy details.",
        type="lesson", scope="project", project=project,
        source="user_requested", tags=["x"],
    )
    b = core.remember(
        content="# beta strategy\nkeyword alpha strategy details also here.",
        type="lesson", scope="project", project=project,
        source="user_requested", tags=["x"],
    )

    core.apply_feedback([b.id], "useful")
    core.apply_feedback([b.id], "useful")
    core.apply_feedback([b.id], "useful")

    hits = idx.recall("alpha strategy", project=project)
    ids = [h.memory.id for h in hits]
    assert b.id in ids and a.id in ids
    assert ids.index(b.id) < ids.index(a.id), "useful memory should rank above equal peer"

    updated_b = core.find_memory(b.id)
    assert updated_b.used == 3


# ---------------------------------------------------------------------------
# Ranking floor: new zero-feedback memory is not buried
# ---------------------------------------------------------------------------

def test_new_memory_with_zero_feedback_not_buried():
    core, idx = _mods()
    core.init_vault()

    project = "p"
    old = core.remember(
        content="# well-worn tip\nshared payload distinctive keyword tip.",
        type="lesson", scope="project", project=project,
        source="user_requested",
    )
    for _ in range(5):
        core.apply_feedback([old.id], "useful")

    fresh = core.remember(
        content="# brand new insight\nshared payload distinctive keyword insight.",
        type="lesson", scope="project", project=project,
        source="user_requested",
    )
    hits = idx.recall("shared payload distinctive keyword", project=project)
    ids = [h.memory.id for h in hits]
    assert fresh.id in ids, "fresh memory disappeared entirely"
    # Feedback boost caps at 1 + 0.4*ln(1+5) ≈ 1.72 so fresh (boost 1.0) is
    # never buried more than one slot below the well-worn tip.
    assert ids.index(fresh.id) <= ids.index(old.id) + 1


# ---------------------------------------------------------------------------
# Index deleted → auto-rebuilt, recall still works
# ---------------------------------------------------------------------------

def test_index_deletion_triggers_silent_rebuild():
    core, idx = _mods()
    core.init_vault()

    mem = core.remember(
        content="# rebuild lesson\nresilient index rebuild lesson body.",
        type="lesson", scope="global", source="user_requested",
    )

    # Nuke the index. Vault (source of truth) is untouched.
    core.index_path().unlink()

    hits = idx.recall("resilient index rebuild")
    assert mem.id in [h.memory.id for h in hits]
    assert core.index_path().exists()


# ---------------------------------------------------------------------------
# MAP.md regeneration is deterministic and reflects state
# ---------------------------------------------------------------------------

def test_map_md_regenerated_on_write():
    core, _idx = _mods()
    core.init_vault()

    core.remember(
        content="# alpha\nalpha body.",
        type="preference", scope="global",
        source="user_requested", tags=["style"],
    )
    core.remember(
        content="# beta\nbeta body.",
        type="lesson", scope="project", project="proj-a",
        source="user_requested", tags=["style"],
    )

    text = core.map_path().read_text(encoding="utf-8")
    assert "proj-a" in text
    assert "style" in text
    assert "alpha" in text or "beta" in text


# ---------------------------------------------------------------------------
# CLI smoke test — the requested end-to-end pipeline
# ---------------------------------------------------------------------------

def test_cli_end_to_end_smoke():
    from theatrum import cli

    rc = cli.main(["init"])
    assert rc == 0

    rc = cli.main([
        "remember",
        "# cli smoke lesson\ncli smoke lesson body content.",
        "--type", "lesson",
        "--scope", "global",
        "--tags", "cli,smoke",
        "--title", "cli smoke",
    ])
    assert rc == 0

    rc = cli.main(["recall", "cli smoke"])
    assert rc == 0

    rc = cli.main(["doctor"])
    assert rc == 0


# ---------------------------------------------------------------------------
# Project identity: git remote normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("git@github.com:acme/repo.git", "github.com/acme/repo"),
    ("https://GitHub.com/acme/repo.git", "github.com/acme/repo"),
    ("https://user:token@gitlab.com/g/sub/repo", "gitlab.com/g/sub/repo"),
    ("ssh://git@github.com/acme/repo", "github.com/acme/repo"),
    ("", None),
    ("not a url", None),
])
def test_normalize_git_remote(url, expected):
    core, _idx = _mods()
    assert core.normalize_git_remote(url) == expected


# ---------------------------------------------------------------------------
# Codex connect/disconnect leaves other keys alone and backs up
# ---------------------------------------------------------------------------

def test_codex_connect_disconnect_preserves_other_keys(monkeypatch):
    core, _idx = _mods()
    from theatrum import connect as connect_mod

    core.init_vault()
    codex_dir = Path(os.environ["HOME"]) / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    cfg = codex_dir / "config.toml"
    cfg.write_text(
        '[other]\nkeep = "me"\n\n[mcp_servers.other]\ncommand = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(connect_mod, "_CODEX_CONFIG", cfg)

    connect_mod._connect_codex()
    text = cfg.read_text(encoding="utf-8")
    assert 'keep = "me"' in text
    assert "[mcp_servers.other]" in text
    assert "[mcp_servers.theatrum]" in text

    connect_mod._disconnect_codex()
    text2 = cfg.read_text(encoding="utf-8")
    assert 'keep = "me"' in text2
    assert "[mcp_servers.other]" in text2
    assert "[mcp_servers.theatrum]" not in text2

    backups = list(codex_dir.glob("config.toml.bak-*"))
    assert len(backups) >= 2


# ---------------------------------------------------------------------------
# T1: Path traversal rejected, no file written outside vault
# ---------------------------------------------------------------------------

def test_t1_path_traversal_project_id_rejected():
    core, _idx = _mods()
    core.init_vault()

    theatrum_home = core.home()

    bad_ids = ["../evil", "/abs", "a/../../b"]
    for bad in bad_ids:
        raised = False
        try:
            core.remember(
                content="# traversal test\nbody.",
                type="lesson",
                scope="project",
                project=bad,
                source="user_requested",
            )
        except ValueError:
            raised = True
        assert raised, f"Expected ValueError for project={bad!r}"

    # Confirm no file was written outside THEATRUM_HOME
    parent = theatrum_home.parent
    evil = parent / "evil"
    assert not evil.exists(), f"evil directory was created at {evil}"
    # abs path: /abs should not exist (or if it does pre-exist, nothing was written by us)
    # Best we can do: confirm projects_dir only has safe subdirs
    projects = core.projects_dir()
    if projects.exists():
        for child in projects.iterdir():
            # no absolute-path traversal would create a child here, but sanity check
            assert not child.name.startswith(".."), f"suspicious dir in projects: {child}"


# ---------------------------------------------------------------------------
# T2: recall with project=None returns global only, never project-scoped
# ---------------------------------------------------------------------------

def test_t2_recall_no_project_returns_global_only():
    core, idx = _mods()
    core.init_vault()

    # Create a project-scoped memory that matches the query
    project_mem = core.remember(
        content="# secret project thing\nproject scoped banana query term.",
        type="lesson",
        scope="project",
        project="github.com/acme/x",
        source="user_requested",
    )
    # Create a global memory that matches
    global_mem = core.remember(
        content="# global thing\nglobal banana query term here.",
        type="lesson",
        scope="global",
        source="user_requested",
    )

    hits = idx.recall("banana query term")  # project=None
    ids = [h.memory.id for h in hits]

    assert project_mem.id not in ids, \
        "project-scoped memory must not appear when project=None"
    assert global_mem.id in ids, \
        "global memory must still appear when project=None"


# ---------------------------------------------------------------------------
# T3: nasty queries don't crash; CJK query matches CJK memory
# ---------------------------------------------------------------------------

def test_t3_nasty_queries_dont_crash():
    core, idx = _mods()
    core.init_vault()

    # Create a CJK memory
    cjk_mem = core.remember(
        content="# CJK test\n数据库索引测试内容。",
        type="lesson",
        scope="global",
        source="user_requested",
    )

    # Nasty queries must not raise
    for query in ['"', 'NEAR OR NOT', 'a\nb']:
        hits = idx.recall(query)
        assert isinstance(hits, list), f"recall({query!r}) did not return a list"

    # CJK query must still match CJK memory (trigram sanity)
    hits = idx.recall("数据库索引")
    ids = [h.memory.id for h in hits]
    assert cjk_mem.id in ids, "CJK query did not match CJK memory via trigram index"


# ---------------------------------------------------------------------------
# T4: frontmatter round-trip with nasty body content
# ---------------------------------------------------------------------------

def test_t4_frontmatter_roundtrip_nasty_body():
    core, _idx = _mods()
    core.init_vault()

    nasty_body = '---\nthis starts with a fence\n"quoted" and colons: here\nnewline\nCJK: 你好世界\n'
    mem = core.remember(
        content=nasty_body,
        type="lesson",
        scope="global",
        source="user_requested",
    )
    assert mem.path is not None and mem.path.exists()

    reloaded = core.read_memory(mem.path)
    assert reloaded is not None, "read_memory returned None after write"
    assert reloaded.id == mem.id
    assert reloaded.type == mem.type
    assert reloaded.scope == mem.scope
    assert reloaded.status == mem.status
    assert reloaded.confidence == mem.confidence
    assert reloaded.created == mem.created
    # Body must survive round-trip verbatim (modulo trailing newline normalization)
    assert reloaded.body.strip() == nasty_body.strip(), \
        f"body mismatch:\ngot:      {reloaded.body!r}\nexpected: {nasty_body!r}"


# ---------------------------------------------------------------------------
# T5: id collision — two memories with same title get distinct ids, both files exist
# ---------------------------------------------------------------------------

def test_t5_id_collision_both_files_exist():
    core, _idx = _mods()
    core.init_vault()

    title = "duplicate title collision test"
    a = core.remember(
        content=f"# {title}\nbody one.",
        type="lesson",
        scope="global",
        source="user_requested",
        title_hint=title,
    )
    b = core.remember(
        content=f"# {title}\nbody two.",
        type="lesson",
        scope="global",
        source="user_requested",
        title_hint=title,
    )

    assert a.id != b.id, f"Both memories got the same id: {a.id!r}"
    assert a.path is not None and a.path.exists(), f"File for memory A not found: {a.path}"
    assert b.path is not None and b.path.exists(), f"File for memory B not found: {b.path}"


# ---------------------------------------------------------------------------
# T6: explicit title persists in frontmatter and survives a reload;
#     without it, title() falls back to the first heading.
# ---------------------------------------------------------------------------

def test_t6_explicit_title_roundtrip():
    core, _idx = _mods()
    core.init_vault()

    titled = core.remember(
        content="## Problem\ntemplate body starts with a section header.",
        type="lesson",
        scope="global",
        source="user_requested",
        title_hint="my real title",
    )
    reloaded = core.read_memory(titled.path)
    assert reloaded.title() == "my real title", reloaded.title()

    untitled = core.remember(
        content="## Problem\nno explicit title given.",
        type="lesson",
        scope="global",
        source="user_requested",
    )
    reloaded2 = core.read_memory(untitled.path)
    assert reloaded2.title() == "Problem", reloaded2.title()
