# Theatrum V1 Master Plan

> **One memory palace. Every agent.**

This is the execution baseline for Theatrum, revised 2026-07-10 after the vision review. It translates the project anchor into a V1 roadmap. Implementation details may still change through ADRs and evidence.

## 0. What Theatrum is, in one sentence

A user-owned second brain for agent collaboration: agents deposit **distilled experience**, and any agent retrieves the most useful part of it under a minimal token budget.

Everything in this plan serves one call:

> **`memory_context` — given the current task and a token budget, return a map plus the most relevant experience units.**

The vault, capture, MCP plumbing, and connectors are supply lines for that call. If `memory_context` is not obviously useful, Theatrum degrades into a note pile nobody reads.

**Landscape note (2026-07):** existing agent-memory systems are either heavy (mem0, Letta, Zep/Graphiti, cognee — LLM extraction pipelines, vector stores, managed backends) or Markdown-adjacent but embedding-dependent (basic-memory). The combination Theatrum targets — no LLM extraction, no embeddings, Markdown as the canonical record, MCP-shared across agents — is currently an open gap.

## 1. Golden scenarios

V1 exists to make four flows dependable:

1. Claude Code saves a project decision and Codex can retrieve it in the same project.
2. A user saves a global preference and every connected agent can use it across projects.
3. Memory from one project is never silently injected into another project.
4. An agent distills a synthesis from several earlier memories; the result is stored with `derived_from` links and the full chain is visible in Obsidian. (The knowledge flywheel.)

These are the end-to-end acceptance scenarios for the first release, implemented as tests against an isolated temporary `$HOME`.

## 2. Memory = experience units, not notes

The default canonical store is `~/.theatrum/vault/`:

```text
vault/
  MAP.md                    # auto-maintained overview (see §4)
  global/
  projects/<project-id>/
  inbox/                    # agent-proposed memories awaiting review
```

Memory **type** lives in frontmatter, not in the directory tree. Typed subdirectories (`decisions/`, `lessons/`, `agents/`, `handoffs/`) from the earlier draft are dropped: scope decides placement, type decides shape.

Types: `preference | decision | lesson | solution | synthesis | project-summary`.

A lesson/solution unit is a complete experience, not a flat sentence:

```markdown
---
id: 20260710-fts5-chinese
type: lesson
scope: project
project: theatrum
tags: [sqlite, fts5, search]
created: 2026-07-10
source: claude-code            # user_requested | agent_inferred
status: active                 # active | proposed | superseded
confidence: high
derived_from: []
superseded_by: null            # corrections point forward instead of rewriting the past
used: 0
dead_end: 0
---

## Problem
FTS5 default tokenizer handles CJK poorly.

## Tried
- jieba custom tokenizer → works, heavy dependency
- unicode61 per-char → too much recall noise

## Worked
FTS5 trigram tokenizer: zero deps, good enough precision.

## Takeaway
Don't add a segmentation library until trigram measurably fails.
```

Markdown is the source of truth. The FTS index, MAP.md statistics, and any future graph or vector index are disposable derived data. Project identity prefers a normalized Git remote, with a locally registered path mapping as fallback; no fuzzy auto-matching — a wrong project match is worse than no match (scenario 3).

## 3. The knowledge flywheel

```text
solve problem with agent
  → capture experience (remember)
  → distill (context --deep → agent synthesizes → remember --derived-from)
  → retrieve on the next task (context)
  → feedback marks what helped (feedback)
  → ranking improves → better retrieval → better syntheses
```

- **Capture:** explicit. Content the user asked to remember becomes `active` immediately; agent-inferred memories land in `inbox/` as `proposed` until approved.
- **Distill:** `memory_context(topic, deep=true)` packs *all* related units including failed attempts; the agent synthesizes; the result is saved as `type: synthesis` with `derived_from` provenance.
- **Feedback:** after using a context pack, the agent reports which memories helped (`useful`) or misled (`dead_end`). Counters feed ranking.

Theatrum never runs an LLM itself. The intelligence stays on the agent side; Theatrum stores, ranks, and packs. This keeps the core local-first with zero model-API dependency.

**Honesty note:** the MCP server cannot verify the `source` field — it trusts the calling agent's declaration. Anti-pollution is enforced by inbox review and Git diff, not by the protocol.

## 4. Retrieval and ranking — the key point

**Map-first.** `MAP.md` is an auto-maintained overview: which projects exist, which topics have the densest experience, what changed recently. It is the first ~300 tokens of every context pack, so an agent orients itself before drilling down. It doubles as the Obsidian home dashboard.

**Ranking (V1, no embeddings):**

1. Hard filters: scope, project, `status: active`.
2. Score — multiplicative boosts over BM25 (additive mixing of raw BM25 is unstable because FTS5 scores are not comparable across queries):

   ```text
   score = relevance × recency × confidence_boost × scope_boost × feedback_boost

   relevance        = -bm25(fts)                     # FTS5 returns negative; lower = better
   recency          = 0.5 + 0.5·exp(-0.1·age_days)   # floored at 0.5 — old memories never die
   confidence_boost = 1.0 + 0.3·confidence           # confidence ∈ [0, 1]
   scope_boost      = 1.2 if project match else 1.0
   feedback_boost   = max(0.8, 1 + 0.4·ln(1+useful) − 0.2·ln(1+dead_end))
                     # log-smoothed and floored: new memories start neutral (no Matthew effect)
   ```

3. Dedupe, then cut deterministically at the caller's token budget (chars/4 estimate).

Text relevance stays the dominant signal: every boost has a floor, so metadata tunes the order but can never bury a strong BM25 match. All parameters above are starting points, expected to be tuned against real vault data.

The feedback loop is borrowed from graphify's `save-result --outcome`: retrieval quality compounds with use, which is what makes the vault a second brain instead of an archive.

Future layers stay optional and derived: full-text → vector → knowledge graph. `derived_from` + `tags` + backlinks already form an implicit graph that Obsidian renders for free; a real graph engine waits until FTS5 provably falls short.

## 5. Minimal CLI

```text
theatrum init
theatrum remember      # typed, structured; --type, --derived-from
theatrum recall
theatrum context       # same engine as MCP memory_context
theatrum review        # filtered listing for human curation
theatrum approve       # promote inbox items
theatrum forget
theatrum doctor
theatrum connect / disconnect
```

Install path stays three steps: `pipx install theatrum-memory && theatrum init && theatrum connect codex claude`. `connect` backs up host config before touching it; `doctor` checks vault, index, MCP wiring, and project identity.

## 6. MCP tools — four in V1

- `memory_remember` (params: type, scope, source, derived_from)
- `memory_recall`
- `memory_context` (params: budget, deep)
- `memory_feedback` (params: memory ids, outcome)

Deferred: `memory_handoff`, `memory_correct`, `memory_forget` — the golden scenarios don't need them; the CLI covers correction and deletion in V1. Vendor-owned SQLite/JSONL/session formats are never runtime dependencies.

## 7. Obsidian as the human control plane

Free by construction: the vault is plain Markdown, `MAP.md` is the dashboard, backlinks render `derived_from` chains, `inbox/` is the review queue. Templates ship with `init`. Dataview enhancements and a web UI are deferred until core workflows prove the need.

## 8. Safety and deployment

- Local stdio MCP by default; no listening network port.
- Exclude credentials, tokens, `.env`, and known secret paths from import and capture.
- Atomic writes; back up host configuration before every integration change; complete `disconnect` path.
- Dependency budget: `mcp` + `pyyaml`. CLI on argparse, search on stdlib sqlite3.
- Linux and macOS first; Windows via WSL. Git sync is opt-in, canonical-Markdown-only, conflict-stopping, and rebuilds derived state locally.

## 9. Delivery: vertical slice first

Milestones are slices of the golden scenarios, not horizontal layers.

- **S1 — Vertical slice:** `init` + `remember` + `recall` + `context` + MCP (4 tools) + `connect` for Claude Code and Codex. Golden scenarios 1–3 pass as tests in an isolated `$HOME`.
- **S2 — Flywheel:** `review`/`approve` + inbox flow, feedback counters in ranking, MAP.md generation. Scenario 4 passes.
- **S3 — Migration:** read-only importers (Claude Code memory dirs, Codex guidance, generic Markdown/Obsidian) with dry-run preview, provenance, dedupe, secret filtering.
- **S4 — Distribution:** pipx/uv polish, doctor coverage, backup/recovery, docs, and opt-in Git vault sync.
- **S5 — Scale layer (only if needed):** local embeddings, hybrid retrieval, graph index — without changing the canonical Markdown model.

## 10. V1 completion criteria

A person can install Theatrum, connect Codex and Claude Code, save a durable experience with one agent, retrieve it with the other under the correct scope and token budget, distill a synthesis from earlier memories with provenance intact, inspect the exact Markdown in Obsidian or a text editor, and correct, recover, or disconnect using ordinary local tools.
