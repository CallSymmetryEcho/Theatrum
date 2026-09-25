"""
Retrieval regressions found by replaying a real, mostly-Chinese vault:
unspaced CJK questions and 2-char terms returned nothing, misspelled proper
nouns returned nothing, the token budget undercounted CJK text, and
mixed-language titles lost their Chinese part in the id. Synthetic data only.
"""

from __future__ import annotations

import sqlite3
from importlib import reload

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("THEATRUM_HOME", str(tmp_path / "theatrum"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    import theatrum.core as core_mod
    reload(core_mod)
    import theatrum.index as index_mod
    reload(index_mod)
    core_mod.init_vault()
    yield


def _mods():
    import theatrum.core as core_mod
    import theatrum.index as index_mod
    return core_mod, index_mod


def _remember(content, *, scope="global", project=None, title=None, tags=()):
    core, _ = _mods()
    return core.remember(
        content=content, type="lesson", scope=scope, project=project,
        tags=list(tags), source="user_requested", title_hint=title,
    )


def _ids(query, **kw):
    _, idx = _mods()
    return [h.memory.id for h in idx.recall(query, **kw)]


# ---------------------------------------------------------------------------
# CJK: unspaced questions and 2-char words
# ---------------------------------------------------------------------------

def test_unspaced_chinese_question_matches():
    polish = _remember("论文润色和学术翻译：先读技能说明，再按任务选择。", title="论文润色技能")
    _remember("工作站远程连入排查：先备份日志，再加固 SSH。", title="远程连入排查")

    ids = _ids("帮我润色论文用什么技能")
    assert ids and ids[0] == polish.id, ids


def test_two_char_terms_match():
    mem = _remember("正式绘图读 T7 移动硬盘上的数据；H5 映射见 DATA_LINKS。", title="绘图数据来源")

    for query in ["绘图", "T7", "H5", "数据"]:
        assert mem.id in _ids(query), query


def test_function_words_alone_match_nothing():
    _remember("什么都可以记录在这个地方。", title="杂项")
    assert _ids("什么") == []
    assert _ids("what is this") == []


# ---------------------------------------------------------------------------
# Spelling-tolerant fallback
# ---------------------------------------------------------------------------

def test_misspelled_proper_noun_falls_back_to_fuzzy():
    mem = _remember("Run backups on the bsuperstation workstation over ssh.", title="backup host")

    for typo in ["bsuperstaton", "buperstation", "bsuperstatoin"]:
        assert mem.id in _ids(typo), typo


def test_fuzzy_fallback_does_not_return_junk():
    _remember("Gesture control reached the render loop; enrichment_control figure.", title="misc")
    _remember("Past results: paste the output into the report.", title="notes")

    for query in ["kubernetes ingress controller", "react hooks rerender", "recipe for pasta"]:
        assert _ids(query) == [], query


def test_exact_match_suppresses_fuzzy():
    exact = _remember("elabftw restore runbook", title="elabftw restore")
    near = _remember("elabftv is a typo that appears in old notes", title="old typo")

    ids = _ids("elabftw")
    assert exact.id in ids and near.id not in ids, ids


# ---------------------------------------------------------------------------
# Project isolation: withheld matches are named, never included
# ---------------------------------------------------------------------------

def test_other_projects_named_not_included():
    _, idx = _mods()
    secret_body = "eLabFTW migration: run MySQL as UID 1000 on fuseblk mounts."
    _remember(secret_body, scope="project", project="github.com/acme/lab", title="elabftw uid")

    for project in [None, "github.com/acme/other"]:
        result = idx.search("elabftw", project=project)
        assert result.hits == []
        assert result.other_projects == {"github.com/acme/lab": 1}

        pack = idx.build_context("elabftw", project=project)
        assert "github.com/acme/lab" in pack
        assert "UID 1000" not in pack  # content never crosses the boundary

    # Asking explicitly for that project returns it.
    assert idx.search("elabftw", project="github.com/acme/lab").hits


def test_cli_recall_prints_other_projects_hint(capsys):
    from theatrum.cli import main

    _remember("sEMG sampling rate is 250Hz, not 1000Hz.", scope="project",
              project="github.com/acme/band", title="semg rate")
    assert main(["recall", "sEMG"]) == 0
    out = capsys.readouterr().out
    assert "no matches" in out
    assert "github.com/acme/band" in out and "250Hz" not in out


# ---------------------------------------------------------------------------
# Token budget counts CJK honestly
# ---------------------------------------------------------------------------

def test_estimate_tokens_counts_cjk_per_character():
    _, idx = _mods()
    assert idx.estimate_tokens("中文" * 100) == 200
    assert idx.estimate_tokens("abcd" * 100) == 100


def test_cjk_memory_respects_budget():
    _, idx = _mods()
    # ~1000 CJK characters ≈ 1000 tokens (chars/4 would have called it ~250).
    body = "## 经验\n" + "迁移前先确认路径属于哪台主机，再只读盘点远端状态。" * 40
    _remember(body, title="先确认路径属于哪台主机")

    assert "只读盘点远端状态" not in idx.build_context("确认路径", budget=800)
    assert "只读盘点远端状态" in idx.build_context("确认路径", budget=2000)


# ---------------------------------------------------------------------------
# Mixed-language titles keep their original script in the id
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title, expected_tail", [
    ("凭证与Skill能力必须分离", "凭证与skill能力必须分离"),
    ("安全架构：命令网关 + L0 武装锁", "安全架构-命令网关-l0-武装锁"),
    ("Obsidian vault 目录", "obsidian-vault-目录"),
    ("Café crème", "cafe-creme"),
    ("broken default python3", "broken-default-python3"),
])
def test_mixed_language_title_keeps_script(title, expected_tail):
    core, _ = _mods()
    assert core.make_id(title).split("-", 1)[1] == expected_tail


# ---------------------------------------------------------------------------
# Upgrade: an index built by the previous schema rebuilds silently
# ---------------------------------------------------------------------------

def test_schema_v1_index_rebuilds_with_terms_table():
    core, idx = _mods()
    mem = _remember("论文绘图先读技能说明。", title="绘图技能")

    # Simulate a pre-upgrade index: no terms table, schema_version 1.
    conn = sqlite3.connect(str(core.index_path()))
    conn.execute("DROP TABLE memories_terms_vocab")
    conn.execute("DROP TABLE memories_terms")
    conn.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
    conn.commit()
    conn.close()

    assert mem.id in _ids("绘图")
