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
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from . import core


# Bump when the frontmatter / index schema changes so stale indexes rebuild.
INDEX_SCHEMA_VERSION = 2


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
-- Word-level terms (see _terms): latin words of any length plus CJK bigrams.
-- Trigram alone can't match 2-char words ("论文", "T7") or unspaced CJK prose.
CREATE VIRTUAL TABLE IF NOT EXISTS memories_terms USING fts5(
    id UNINDEXED,
    title,
    body,
    tags,
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_terms_vocab USING fts5vocab(memories_terms, 'row');
INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', '{INDEX_SCHEMA_VERSION}');
"""


# ---------------------------------------------------------------------------
# Text segmentation (shared by indexing and querying)
# ---------------------------------------------------------------------------

# Scripts written without spaces, where most words are 1–2 characters.
_CJK = "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff"
_TERM_RE = re.compile(rf"([{_CJK}]+)|([^\W_{_CJK}]+)")
_CJK_CHAR_RE = re.compile(rf"[{_CJK}\u3000-\u303f\uff00-\uffef]")  # + CJK punctuation

# Function words that match nearly everything and carry no topic.
_STOP_TERMS = frozenset(
    "a an and are as at be but by can do does for from how i in is it me my of on or "
    "so that the this to was we what when where which who why with you your".split()
    + "什么 怎么 哪里 哪个 在哪 为什 如何 一下 帮我 请问 这个 那个 我的".split()
)


def _terms(text: str) -> list[str]:
    """Latin/digit words as-is; each CJK run as overlapping bigrams."""
    text = unicodedata.normalize("NFKC", text).lower()
    out: list[str] = []
    for cjk, word in _TERM_RE.findall(text):
        if word:
            out.append(word)
        elif len(cjk) == 1:
            out.append(cjk)
        else:
            out.extend(cjk[i:i + 2] for i in range(len(cjk) - 1))
    return out


def _terms_text(text: str) -> str:
    return " ".join(_terms(text))


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
    conn.execute("DELETE FROM memories_terms WHERE id=?", (m.id,))
    conn.execute(
        "INSERT INTO memories_terms(id, title, body, tags) VALUES (?,?,?,?)",
        (m.id, _terms_text(m.title()), _terms_text(m.body), _terms_text(tags_str)),
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
        conn.execute("DELETE FROM memories_terms WHERE id=?", (mem_id,))
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


def _clean(raw: str) -> str:
    """Strip control characters (U+0000–U+001F and U+007F), incl. newlines."""
    return re.sub(r"[\x00-\x1f\x7f]", " ", raw)


_SCRIPT_BOUNDARY_RE = re.compile(rf"(?<=[{_CJK}])(?=[^{_CJK}])|(?<=[^{_CJK}])(?=[{_CJK}])")


def _fts_query(raw: str) -> str:
    """
    Turn user text into a safe trigram (substring) MATCH expression.
    Trigram tokenizer needs 3+ chars per term. Terms are OR-joined; the
    engine scores intersection strongly via BM25 already.

    Sanitization steps:
    1. Strip control characters and double quotes from the raw query.
    2. Split on whitespace and at CJK/latin boundaries ("去busperstation" →
       "去", "busperstation"); strip edge punctuation; drop function words.
    3. Wrap every surviving token (3+ chars) as a quoted phrase.
    4. If no tokens survive, return "" (empty string) so the caller skips
       the MATCH.
    """
    tokens: list[str] = []
    for chunk in _clean(raw).replace('"', " ").split():
        for part in _SCRIPT_BOUNDARY_RE.split(chunk):
            part = re.sub(r"^[\W_]+|[\W_]+$", "", part)
            if len(part) >= 3 and part.lower() not in _STOP_TERMS and part not in tokens:
                tokens.append(part)
    return " OR ".join(f'"{t}"' for t in tokens)


def _terms_query(raw: str) -> str:
    """Word/bigram MATCH expression; single chars and function words dropped."""
    terms: list[str] = []
    for t in _terms(_clean(raw)):
        if len(t) >= 2 and t not in _STOP_TERMS and t not in terms:
            terms.append(t)
    return " OR ".join(f'"{t}"' for t in terms)


def _match(conn: sqlite3.Connection, table: str, expr: str) -> dict[str, float]:
    """id → relevance (negated bm25: higher = better) for one FTS table."""
    if not expr:
        return {}
    try:
        rows = conn.execute(
            f"SELECT id, bm25({table}) AS bm FROM {table} WHERE {table} MATCH ?",
            (expr,),
        ).fetchall()
    except sqlite3.OperationalError:  # ponytail: should now be unreachable after sanitization
        return {}
    return {row["id"]: -float(row["bm"]) for row in rows}


_FUZZY_MIN_SIMILARITY = 0.7
_FUZZY_MIN_WORD_LEN = 5


def _padded_grams(word: str) -> set[str]:
    padded = f"  {word} "  # pg_trgm-style padding weights word edges
    return {padded[i:i + 3] for i in range(len(padded) - 2)}


def _fuzzy(conn: sqlite3.Connection, raw: str) -> dict[str, float]:
    """
    Spelling-tolerant fallback for the user's own proper nouns ("bsuperstaton"
    → "bsuperstation"). Each query word (5+ latin chars) is compared with the
    indexed vocabulary by padded-trigram Dice similarity (≥ 0.7); a memory
    qualifies only if it matches a strict majority of those words.
    Relevance = summed similarity. Runs only when nothing in scope
    matched exactly, so it never dilutes exact results.
    """
    words = [t for t in dict.fromkeys(_terms(_clean(raw)))
             if len(t) >= _FUZZY_MIN_WORD_LEN and t not in _STOP_TERMS
             and not _CJK_CHAR_RE.search(t)]
    if not words:
        return {}
    vocab = [
        (term, _padded_grams(term))
        for (term,) in conn.execute("SELECT term FROM memories_terms_vocab")
        if len(term) >= 3 and not _CJK_CHAR_RE.search(term)
    ]
    best: dict[str, dict[str, float]] = {}  # memory id → query word → similarity
    for w in words:
        wg = _padded_grams(w)
        for term, tg in vocab:
            sim = 2 * len(wg & tg) / (len(wg) + len(tg))
            if sim < _FUZZY_MIN_SIMILARITY:
                continue
            for (mem_id,) in conn.execute(
                "SELECT id FROM memories_terms WHERE memories_terms MATCH ?", (f'"{term}"',)
            ):
                per_word = best.setdefault(mem_id, {})
                per_word[w] = max(per_word.get(w, 0.0), sim)
    need = len(words) // 2 + 1
    return {mid: sum(s.values()) for mid, s in best.items() if len(s) >= need}


@dataclass
class Hit:
    memory: core.Memory
    score: float
    relevance: float
    recency: float
    confidence_boost: float
    scope_boost: float
    feedback_boost: float


@dataclass
class SearchResult:
    hits: list[Hit]
    # project id → matching memories withheld by project isolation (names and
    # counts only, never content) so callers can offer an explicit read.
    other_projects: dict[str, int] = field(default_factory=dict)


def _load(mem_id: str, path: str | None) -> core.Memory | None:
    """Read by indexed path; fall back to a vault scan if the file moved."""
    if path:
        mem = core.read_memory(Path(path))
        if mem is not None and mem.id == mem_id:
            return mem
    return core.find_memory(mem_id)


def _rank(
    conn: sqlite3.Connection,
    relevance_by_id: dict[str, float],
    *,
    scope: str | None,
    project: str | None,
    limit: int,
    include_proposed: bool,
) -> SearchResult:
    paths: dict[str, str | None] = {}
    if relevance_by_id:
        placeholders = ",".join("?" * len(relevance_by_id))
        paths = {
            row["id"]: row["path"]
            for row in conn.execute(
                f"SELECT id, path FROM memories WHERE id IN ({placeholders})",
                list(relevance_by_id),
            )
        }

    hits: list[Hit] = []
    other_projects: dict[str, int] = {}
    for mem_id, relevance in relevance_by_id.items():
        mem = _load(mem_id, paths.get(mem_id))
        if mem is None:
            continue
        if not include_proposed and mem.status != "active":
            continue
        # Scope isolation. Project X memories NEVER show up under project Y.
        # When project is None: return global memories only — no project-scoped
        # memories are mixed in regardless of query match.
        if mem.scope == "project" and (project is None or mem.project != project):
            if scope != "global" and mem.project:
                other_projects[mem.project] = other_projects.get(mem.project, 0) + 1
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
    return SearchResult(hits[: max(0, int(limit))], other_projects)


def search(
    query: str,
    *,
    scope: str | None = None,
    project: str | None = None,
    limit: int = 10,
    include_proposed: bool = False,
) -> SearchResult:
    """
    Ranked search. Formula per V1 master plan §4:

        score = relevance × recency × confidence_boost × scope_boost × feedback_boost

    ``relevance`` sums two BM25 signals: trigram substring matches and
    word/CJK-bigram matches. If nothing in scope matches, the spelling-tolerant
    ``_fuzzy`` pass runs instead.

    Hard filters:
    - ``status: active`` (unless ``include_proposed``)
    - scope isolation: project X memories never returned when querying project Y
    - **when ``project`` is None, project-scoped memories are EXCLUDED entirely
      (global-scope only).** Cross-project mixing is impossible through any query path.
    """
    trigram_expr = _fts_query(query)
    terms_expr = _terms_query(query)
    if not trigram_expr and not terms_expr:
        return SearchResult([])
    ensure_index()
    conn = _connect()
    opts = dict(scope=scope, project=project, limit=limit, include_proposed=include_proposed)
    try:
        relevance: dict[str, float] = {}
        for table, expr in (("memories_fts", trigram_expr), ("memories_terms", terms_expr)):
            for mem_id, r in _match(conn, table, expr).items():
                relevance[mem_id] = relevance.get(mem_id, 0.0) + r
        result = _rank(conn, relevance, **opts)
        if not result.hits:
            fuzzy = _rank(conn, _fuzzy(conn, query), **opts)
            for pid, n in result.other_projects.items():
                fuzzy.other_projects[pid] = max(n, fuzzy.other_projects.get(pid, 0))
            result = fuzzy
    finally:
        conn.close()
    return result


def recall(
    query: str,
    *,
    scope: str | None = None,
    project: str | None = None,
    limit: int = 10,
    include_proposed: bool = False,
) -> list[Hit]:
    """Ranked hits only; see ``search`` for the formula and hard filters."""
    return search(
        query, scope=scope, project=project, limit=limit,
        include_proposed=include_proposed,
    ).hits


# ---------------------------------------------------------------------------
# Context packing
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """
    Deterministic, cheap estimate: ~4 chars/token for latin text and 1 token
    per CJK character (plain chars/4 undercounts Chinese several-fold).
    """
    cjk = len(_CJK_CHAR_RE.findall(text))
    return max(0, cjk + (len(text) - cjk) // 4)


def other_projects_note(counts: dict[str, int], max_projects: int = 3) -> str:
    """Withheld counts as `a` ×3, `b` ×1 (+2 more); "" when none."""
    if not counts:
        return ""
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:max_projects]
    note = ", ".join(f"`{pid}` ×{n}" for pid, n in top)
    if len(counts) > len(top):
        note += f" (+{len(counts) - len(top)} more)"
    return note


def build_context(
    query: str,
    *,
    budget: int = 2000,
    deep: bool = False,
    project: str | None = None,
) -> str:
    """
    MAP.md header + top ranked memories packed under ``budget`` tokens
    (``estimate_tokens``).

    ``deep=True`` includes ALL matches regardless of ranking cutoff (still
    budget-capped).

    When ``project`` is None, only global-scope memories are returned (same
    contract as ``recall``). Matches withheld from other projects are named in
    a closing line — never their content — so the agent can ask explicitly.
    """
    header = _map_header_snippet()
    parts: list[str] = [header]
    used_tokens = estimate_tokens(header)

    limit = 1000 if deep else 20
    result = search(query, project=project, limit=limit)
    note = other_projects_note(result.other_projects)
    footer = (
        f"_Also matched in other projects (withheld by isolation): {note}. "
        "Pass project=<id> to read them explicitly._"
    ) if note else ""
    reserved = estimate_tokens(footer)

    for h in result.hits:
        section = _pack_memory(h.memory)
        cost = estimate_tokens(section)
        if used_tokens + cost + reserved > budget:
            # Budget cap applies in both regular and deep mode.
            break
        parts.append(section)
        used_tokens += cost
    if footer:
        parts.append(footer)

    return "\n\n".join(parts).rstrip() + "\n"


MAP_HEADER_TOKENS = 300


def _map_header_snippet() -> str:
    """First ~300 tokens of MAP.md (whole lines), or a stub if not generated yet."""
    p = core.map_path()
    if not p.exists():
        return core.DEFAULT_MAP.strip()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return core.DEFAULT_MAP.strip()
    kept: list[str] = []
    used = 0
    for line in text.splitlines():
        used += estimate_tokens(line + "\n")
        if used > MAP_HEADER_TOKENS:
            break
        kept.append(line)
    return "\n".join(kept).rstrip()


def _pack_memory(m: core.Memory) -> str:
    scope_line = f"scope: {m.scope}" + (f" / project: {m.project}" if m.project else "")
    return (
        f"### {m.id} — {m.title()}\n"
        f"_{m.type} · {scope_line} · confidence: {m.confidence} · "
        f"used: {m.used} · dead_end: {m.dead_end}_\n\n"
        f"{m.body.strip()}"
    )
