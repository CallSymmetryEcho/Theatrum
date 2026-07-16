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
- `theatrum sync init [URL] [--remote NAME] [--branch NAME]` — initialize a dedicated Git repository in the vault and configure a private sync target. The URL is optional only when that remote already exists.
- `theatrum sync status` — offline JSON report: target, current branch, cached ahead/behind counts, conflicts, and canonical memory count. Never fetches.
- `theatrum sync run [--remote NAME] [--branch NAME] [--message TEXT] [--no-push] [--allow-secrets]` — commit local canonical Markdown, fetch and integrate the remote, optionally push, then rebuild the local FTS index and `MAP.md`.
- `theatrum serve` — run the MCP stdio server (hosts spawn this).
- `theatrum connect <claude|codex>` — wire the MCP server into a host. Backs up the host config first.
- `theatrum disconnect <claude|codex>` — fully reverse `connect`. Backs up first.
- `theatrum doctor` — health report (vault/index/wiring). Exits non-zero if the vault is missing or the index is broken.

## MCP tools

- `memory_remember(content, type, scope, project=None, tags=None, source="user_requested", derived_from=None, confidence="medium", title=None)` — save a memory. `user_requested` → active; anything else → proposed (inbox, excluded from recall/context until approved).
- `memory_recall(query, scope=None, project=None, limit=10)` — ranked search. Project isolation is a hard filter; `project=None` returns global-only.
- `memory_context(query, budget=2000, deep=False, project=None)` — MAP.md header + top memories packed under `budget` tokens.
- `memory_feedback(ids, outcome)` — increment `used` / `dead_end` counters; feeds ranking.

## Cross-host synchronization

Use an empty private Git repository as the transport. SSH URLs are preferred so credentials are not stored in `.git/config`:

```bash
# Example: create the transport on a trusted server once.
git init --bare /srv/theatrum-vault.git

# Run on every host, including hosts that already contain memories.
theatrum sync init git@trusted-host:/srv/theatrum-vault.git
git -C ~/.theatrum/vault config user.name "Your Name"
git -C ~/.theatrum/vault config user.email "you@example.com"
theatrum sync run
```

The first host seeds the remote. When another non-empty vault joins, Theatrum merges the unrelated initial histories: distinct memory IDs form a union. If both sides contain different content at the same path, Git leaves an explicit conflict and Theatrum exits non-zero without pushing or indexing the conflicted files.

Resolve a stopped sync with normal Git tools inside `~/.theatrum/vault`:

```bash
theatrum sync status
# edit each conflicted Markdown file, then:
git add <resolved-files>
git rebase --continue       # when status says operation: rebase
# or: git commit            # when status says operation: merge
theatrum sync run
```

To abandon instead, use `git rebase --abort` or `git merge --abort` as reported by `sync status`.

Only canonical `global/**/*.md`, `projects/**/*.md`, and `inbox/**/*.md` files are staged. `MAP.md`, `.obsidian/`, `.DS_Store`, `index.db`, and `projects.json` are machine-local. After every successful integration, `index.db` and `MAP.md` are rebuilt from the synchronized Markdown. A conservative secret scan blocks pushes by default; `--allow-secrets` is an explicit escape hatch for false positives, not a recommendation to store credentials in memory.

## Recovery

- `~/.theatrum/index.db` is disposable. Delete it — it rebuilds silently from the vault on the next call.
- Every `connect` / `disconnect` writes a timestamped `*.bak-<YYYYMMDD-HHMMSS>` next to the host config before touching it.
- Run `theatrum sync init <private-git-url>` to make Git the history, review, rollback, and optional cross-host transport for canonical memories.
- `theatrum doctor` prints vault/index health, host wiring, and local sync status. `theatrum sync status` adds branch and cached divergence details without network access.
