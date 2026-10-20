"""
Theatrum FTS index + ranking + context packing.

Split out from ``core`` per the layout budget (core.py exceeded ~500 lines).
The index at ``$THEATRUM_HOME/index.db`` is disposable derived data: everything
here can be rebuilt from the Markdown vault via ``rebuild_index``.
"""

from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone

from . import core


# Bump when the frontmatter / index schema changes so stale indexes rebuild.
INDEX_SCHEMA_VERSION = 1


_INDEX_DDL = f"""
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    type TEXT,
    scope TEXT,
    project TEXT,
    tags TEXT,          -- space-joined for tokenization
    created TEXT,
    source TEXT,
    status TEXT,
    confidence TEXT,
    used INTEGER,
    dead_end INTEGER,
    path TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    id UNINDEXED,
    title,
    body,
    tags,
    tokenize = 'trigram'
);
INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', '{INDEX_SCHEMA_VERSION}');
"""


# ---------------------------------------------------------------------------
# Index lifecycle
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    core.home().mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(core.index_path()))
    conn.row_factory = sqlite3.Row
    return conn


def _schema_ok(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    except sqlite3.DatabaseError:
        return False
    if not row:
        return False
    return str(row[0]) == str(INDEX_SCHEMA_VERSION)


def ensure_index() -> None:
    """Open the index. Rebuild silently if missing or schema-stale."""
    p = core.index_path()
    if not p.exists():
        rebuild_index()
        return
    try:
        conn = _connect()
    except sqlite3.DatabaseError:
        p.unlink(missing_ok=True)
        rebuild_index()
        return
    try:
        if not _schema_ok(conn):
            conn.close()
            p.unlink(missing_ok=True)
            rebuild_index()
            return
    finally:
        try:
            conn.close()
        except Exception:
            pass


def rebuild_index() -> None:
    """Wipe and rebuild the FTS index from the vault. Never touches Markdown."""
    p = core.index_path()
    if p.exists():
        try:
            p.unlink()
        except OSError:
            pass
    conn = _connect()
    try:
        conn.executescript(_INDEX_DDL)
        for m in core.iter_all_memories():
            _index_upsert_conn(conn, m)
        conn.commit()
    finally:
        conn.close()


def _index_upsert_conn(conn: sqlite3.Connection, m: core.Memory) -> None:
    tags_str = " ".join(m.tags)
    conn.execute(
        "INSERT OR REPLACE INTO memories(id,type,scope,project,tags,created,source,"
        "status,confidence,used,dead_end,path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (m.id, m.type, m.scope, m.project, tags_str, m.created, m.source,
         m.status, m.confidence, m.used, m.dead_end, str(m.path) if m.path else None),
    )
    conn.execute("DELETE FROM memories_fts WHERE id=?", (m.id,))
    conn.execute(
        "INSERT INTO memories_fts(id, title, body, tags) VALUES (?,?,?,?)",
        (m.id, m.title(), m.body, tags_str),
    )


def index_upsert(m: core.Memory) -> None:
    ensure_index()
    conn = _connect()
    try:
        _index_upsert_conn(conn, m)
        conn.commit()
    finally:
        conn.close()


def index_delete(mem_id: str) -> None:
    ensure_index()
    conn = _connect()
    try:
        conn.execute("DELETE FROM memories WHERE id=?", (mem_id,))
        conn.execute("DELETE FROM memories_fts WHERE id=?", (mem_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Ranking (V1, no embeddings)
# ---------------------------------------------------------------------------

def _age_days(created: str) -> float:
    try:
        d = date.fromisoformat(created)
    except ValueError:
        return 0.0
    today = datetime.now(timezone.utc).date()
    return max(0.0, (today - d).days)


def _confidence_float(conf: str) -> float:
    return core.CONFIDENCE_TO_FLOAT.get(conf, 0.5)


# Scripts written without spaces between words: kana, CJK ideographs, hangul.
_CJK = "぀-ヿ㐀-䶿一-鿿가-힯豈-﫿"


def _query_terms(raw: str) -> list[str]:
    """
    Query terms with control chars and double quotes removed. Splits on
    whitespace and at CJK/non-CJK boundaries ("eLabFTW迁移" → eLabFTW, 迁移).
    """
    # Remove control characters (U+0000–U+001F and U+007F)
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", raw)
    tokens = re.findall(rf"[{_CJK}]+|[^\s{_CJK}]+", cleaned)
    tokens = [t.replace('"', "") for t in tokens]
    return [t for t in tokens if t]


def _fts_query(raw: str) -> str:
    """
    Turn user text into a safe FTS5 MATCH expression.
    Trigram tokenizer needs 3+ chars per term. Terms are OR-joined; the
    engine scores intersection strongly via BM25 already. Shorter terms are
    handled by the LIKE fallback in ``recall``.

    Sanitization steps:
    1. Strip control characters (including newlines) from the raw query.
    2. Split on whitespace, strip quotes from each token.
    3. Wrap every surviving token as a quoted phrase.
    4. If no tokens survive, return "" (empty string) so the caller skips
       the MATCH.
    """
    tokens = [t for t in _query_terms(raw) if len(t) >= 3]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


def _short_terms(raw: str) -> list[str]:
    """
    Two-char terms the trigram index cannot MATCH: most Chinese words
    (迁移, 绘图) and short codes (T7). One-char terms are dropped as noise.
    Longer CJK runs also contribute overlapping bigrams, so an unspaced
    phrase matches memories holding its words apart (安装技能 → 安装 装技 技能).
    """
    terms: list[str] = []
    for t in _query_terms(raw):
        if len(t) == 2:
            terms.append(t)
        elif len(t) > 2 and re.fullmatch(f"[{_CJK}]+", t):
            # ponytail: bigrams stand in for a word segmenter (no jieba); junk
            # bigrams like 装技 rarely match. Add segmentation if noise hurts.
            terms += [t[i : i + 2] for i in range(len(t) - 1)]
    return list(dict.fromkeys(terms))


# ponytail: flat per-term weight for LIKE hits (BM25 is unavailable for them).
# Tune if short-term hits crowd out real BM25 matches.
SHORT_TERM_WEIGHT = 1.0


@dataclass
class Hit:
    memory: core.Memory
    score: float
    relevance: float
    recency: float
    confidence_boost: float
    scope_boost: float
    feedback_boost: float


def recall(
    query: str,
    *,
    scope: str | None = None,
    project: str | None = None,
    limit: int = 10,
    include_proposed: bool = False,
) -> list[Hit]:
    """
    Ranked search. Formula per V1 master plan §4:

        score = relevance × recency × confidence_boost × scope_boost × feedback_boost

    Hard filters:
    - ``status: active`` (unless ``include_proposed``)
    - scope isolation: project X memories never returned when querying project Y
    - **when ``project`` is None, project-scoped memories are EXCLUDED entirely
      (global-scope only).** Cross-project mixing is impossible through any query path.
    """
    hits, _ = search(
        query, scope=scope, project=project, limit=limit,
        include_proposed=include_proposed,
    )
    return hits


def search(
    query: str,
    *,
    scope: str | None = None,
    project: str | None = None,
    limit: int = 10,
    include_proposed: bool = False,
) -> tuple[list[Hit], dict[str, int]]:
    """
    ``recall`` plus the matches the project filter removed.

    Returns ``(hits, hidden)`` where ``hidden`` maps project id → number of
    matching project-scoped memories excluded because ``project`` is None.
    It is only filled when both ``project`` and ``scope`` are None, so callers
    can point at those projects instead of reporting "nothing found".
    """
    fts_expr = _fts_query(query)
    short_terms = _short_terms(query)
    if not fts_expr and not short_terms:
        return [], {}
    ensure_index()
    relevance_by_id: dict[str, float] = {}
    conn = _connect()
    try:
        if fts_expr:
            try:
                rows = conn.execute(
                    "SELECT memories_fts.id, bm25(memories_fts) AS bm "
                    "FROM memories_fts WHERE memories_fts MATCH ?",
                    (fts_expr,),
                ).fetchall()
            except sqlite3.OperationalError:  # ponytail: should now be unreachable after _fts_query sanitization
                rows = []
            for row in rows:
                # FTS5 bm25 is negative; lower = better, so negate.
                relevance_by_id[row["id"]] = -float(row["bm"])
        for term in short_terms:
            # ponytail: full scan per short term; fine for a personal vault.
            pattern = "%" + re.sub(r"([\\%_])", r"\\\1", term) + "%"
            rows = conn.execute(
                "SELECT id FROM memories_fts WHERE title LIKE ?1 ESCAPE '\\' "
                "OR body LIKE ?1 ESCAPE '\\' OR tags LIKE ?1 ESCAPE '\\'",
                (pattern,),
            ).fetchall()
            for row in rows:
                relevance_by_id[row["id"]] = relevance_by_id.get(row["id"], 0.0) + SHORT_TERM_WEIGHT
    finally:
        conn.close()

    hits: list[Hit] = []
    hidden: dict[str, int] = {}
    for mem_id, relevance in relevance_by_id.items():
        mem = core.find_memory(mem_id)
        if mem is None:
            continue
        if not include_proposed and mem.status != "active":
            continue
        # Scope isolation. Project X memories NEVER show up under project Y.
        # When project is None: return global memories only — no project-scoped
        # memories are mixed in regardless of query match.
        if project is None:
            if mem.scope == "project":
                if scope is None:
                    hidden[mem.project] = hidden.get(mem.project, 0) + 1
                continue
        else:
            if mem.scope == "project" and mem.project != project:
                continue
        if scope is not None:
            if scope == "global" and mem.scope != "global":
                continue
            if scope == "project" and mem.scope != "project":
                continue
        recency = 0.5 + 0.5 * math.exp(-0.1 * _age_days(mem.created))
        conf_boost = 1.0 + 0.3 * _confidence_float(mem.confidence)
        scope_boost = 1.2 if (project and mem.scope == "project" and mem.project == project) else 1.0
        fb = max(0.8, 1.0 + 0.4 * math.log(1 + mem.used) - 0.2 * math.log(1 + mem.dead_end))
        score = relevance * recency * conf_boost * scope_boost * fb
        hits.append(Hit(mem, score, relevance, recency, conf_boost, scope_boost, fb))

    hits.sort(key=lambda h: h.score, reverse=True)
    seen: set[str] = set()
    deduped: list[Hit] = []
    for h in hits:
        if h.memory.id in seen:
            continue
        seen.add(h.memory.id)
        deduped.append(h)
    return deduped[: max(0, int(limit))], hidden


def hidden_hint(hidden: dict[str, int]) -> str:
    """One-line pointer at project-scoped matches a global-only query skipped."""
    if not hidden:
        return ""
    where = ", ".join(f"{p} ({n})" for p, n in sorted(hidden.items()))
    return f"{sum(hidden.values())} more match(es) in project-scoped memories: {where}. Pass project=<id> to see them."


# ---------------------------------------------------------------------------
# Context packing
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Char/4 estimate (deterministic, cheap)."""
    return max(0, len(text) // 4)


def build_context(
    query: str,
    *,
    budget: int = 2000,
    deep: bool = False,
    project: str | None = None,
) -> str:
    """
    MAP.md header + top ranked memories packed under ``budget`` tokens (chars//4).

    ``deep=True`` includes ALL matches regardless of ranking cutoff (still
    budget-capped).

    When ``project`` is None, only global-scope memories are returned (same
    contract as ``recall``).
    """
    header = _map_header_snippet()
    parts: list[str] = [header]
    used_tokens = estimate_tokens(header)

    limit = 1000 if deep else 20
    hits, hidden = search(query, project=project, limit=limit)
    if hidden:
        parts.append(f"_{hidden_hint(hidden)}_")

    for h in hits:
        section = _pack_memory(h.memory)
        cost = estimate_tokens(section)
        if used_tokens + cost > budget:
            # Budget cap applies in both regular and deep mode.
            break
        parts.append(section)
        used_tokens += cost

    return "\n\n".join(parts).rstrip() + "\n"


def _map_header_snippet() -> str:
    """First ~300 tokens of MAP.md, or a stub if it hasn't been generated yet."""
    p = core.map_path()
    if not p.exists():
        return core.DEFAULT_MAP.strip()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return core.DEFAULT_MAP.strip()
    return text[:1200].rstrip()


def _pack_memory(m: core.Memory) -> str:
    scope_line = f"scope: {m.scope}" + (f" / project: {m.project}" if m.project else "")
    return (
        f"### {m.id} — {m.title()}\n"
        f"_{m.type} · {scope_line} · confidence: {m.confidence} · "
        f"used: {m.used} · dead_end: {m.dead_end}_\n\n"
        f"{m.body.strip()}"
    )
