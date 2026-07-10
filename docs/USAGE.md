# Theatrum Usage

Reference card. See the README for the pitch.

## Install

```bash
# preferred: pipx from the GitHub URL
pipx install "git+https://github.com/CallSymmetryEcho/Theatrum"
# or: uv tool install "git+https://github.com/CallSymmetryEcho/Theatrum"

# from source
git clone https://github.com/CallSymmetryEcho/Theatrum && cd Theatrum
uv venv && uv pip install -e .
```

Then wire it up:

```bash
theatrum init
theatrum connect claude
theatrum connect codex
```

## Commands

- `theatrum init` — create `~/.theatrum/vault` (idempotent).
- `theatrum remember <content> --type <t> --scope <global|project> [--project ID] [--tags a,b] [--source user_requested|agent_inferred|imported] [--derived-from ID,...] [--confidence low|medium|high] [--title HINT]` — save a memory. `agent_inferred` and `imported` land in `inbox/` as proposed.
- `theatrum recall <query> [--scope ...] [--project ID] [--limit N]` — ranked search.
- `theatrum context <query> [--budget N] [--deep] [--project ID]` — MAP.md header + top memories packed under a token budget (chars/4).
- `theatrum review` — list proposed (inbox) memories awaiting curation.
- `theatrum approve <id> [<id> ...]` — promote proposed memories to active.
- `theatrum forget <id> [<id> ...]` — delete permanently. Git is the recovery path.
- `theatrum import <claude|codex|markdown> <path> [--scope ...] [--project ID] [--type ...] [--yes]` — read-only import into `inbox/`. Dry-run by default; `--yes` writes. Content-hash dedupe, secret filtering, per-file provenance.
- `theatrum serve` — run the MCP stdio server (hosts spawn this).
- `theatrum connect <claude|codex>` — wire the MCP server into a host. Backs up the host config first.
- `theatrum disconnect <claude|codex>` — fully reverse `connect`. Backs up first.
- `theatrum doctor` — health report (vault/index/wiring). Exits non-zero if the vault is missing or the index is broken.

## MCP tools

- `memory_remember(content, type, scope, project=None, tags=None, source="user_requested", derived_from=None, confidence="medium", title=None)` — save a memory. `user_requested` → active; anything else → proposed (inbox, excluded from recall/context until approved).
- `memory_recall(query, scope=None, project=None, limit=10)` — ranked search. Project isolation is a hard filter; `project=None` returns global-only.
- `memory_context(query, budget=2000, deep=False, project=None)` — MAP.md header + top memories packed under `budget` tokens.
- `memory_feedback(ids, outcome)` — increment `used` / `dead_end` counters; feeds ranking.

## Recovery

- `~/.theatrum/index.db` is disposable. Delete it — it rebuilds silently from the vault on the next call.
- Every `connect` / `disconnect` writes a timestamped `*.bak-<YYYYMMDD-HHMMSS>` next to the host config before touching it.
- Run `git init` inside `~/.theatrum/vault` — history, review, and rollback of every memory with tools you already know. `theatrum init` prints a tip when the vault isn't a git repo yet.
- `theatrum doctor` prints vault existence, index health, whether `theatrum` is on PATH, whether the vault is a git repo, and each host's wiring status.
