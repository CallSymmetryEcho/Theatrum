# Theatrum V1 Master Plan

> **One memory palace. Every agent.**

This document is the first execution baseline for Theatrum. It translates the project anchor into a practical V1 roadmap while preserving the right to revise implementation details through ADRs and evidence.

## 1. Golden scenarios

V1 exists to make three flows dependable:

1. Claude Code saves a project decision and Codex can retrieve it in the same project.
2. A user saves a global preference and every connected agent can use it across projects.
3. Memory from one project is never silently injected into another project.

These are the primary end-to-end acceptance scenarios for the first release.

## 2. Plaintext memory core

The default canonical store is `~/.theatrum/vault/`:

```text
vault/
  global/
  projects/<project-id>/
  agents/<agent-id>/
  decisions/
  lessons/
  handoffs/
  inbox/
```

Each memory is an independent Markdown document with a stable ID, scope, provenance, timestamps, confidence, lifecycle status, and project association where applicable.

Markdown is the source of truth. Search, graph, and future vector indexes are disposable derived data.

Project identity prefers a normalized Git remote and uses a locally registered path identity as fallback. Clones, moved repositories, and worktrees of the same project should resolve to the same project memory where possible.

## 3. Minimal CLI

The initial command surface is:

```text
theatrum init
theatrum remember
theatrum recall
theatrum context
theatrum inspect
theatrum approve
theatrum forget
theatrum doctor
theatrum connect
theatrum disconnect
```

The intended installation path is three steps:

```bash
pipx install theatrum-memory
theatrum init
theatrum connect codex claude
```

`connect` backs up and configures supported agent integrations. `doctor` verifies the vault, permissions, MCP configuration, Git state, project identity, and configuration drift.

## 4. Shared access through MCP

The first stable MCP tool set should remain small:

- `memory_remember`
- `memory_recall`
- `memory_get`
- `memory_context`
- `memory_handoff`
- `memory_correct`
- `memory_forget`

Codex, Claude Code, and future agents access one memory core through MCP and minimal host-level guidance. Vendor-owned SQLite, JSONL, and session formats are not runtime dependencies.

### Write policy

- Content explicitly requested by the user with language such as “remember this” becomes active immediately.
- Memories inferred or summarized automatically by an agent enter `inbox/` with `proposed` status.
- Corrections preserve provenance and supersession history instead of silently rewriting the past.

This balances low-friction explicit memory with protection against memory pollution and poisoning.

## 5. Retrieval and context packing

V1 does not require embeddings. Retrieval begins with:

- frontmatter and scope filters;
- keyword and full-text search;
- ranking by relevance, scope, recency, confidence, and provenance;
- duplicate and stale-memory detection;
- deterministic context packing under a caller-supplied token budget.

`memory_context` returns a compact, source-backed context pack rather than injecting the entire vault.

Future indexing remains layered and optional:

```text
Markdown Vault -> Full-text index
               -> Vector index
               -> Knowledge graph
```

No derived index may become the canonical record.

## 6. Native-memory migration

The first importers are read-only and previewable:

- Claude Code project memory directories;
- Claude Code user-level guidance;
- supported Codex global guidance and public memory interfaces;
- generic Markdown and Obsidian vaults.

Import includes dry-run preview, provenance, deduplication, and sensitive-data checks. Theatrum does not overwrite native agent storage. Undocumented private databases remain outside the write path.

## 7. Obsidian as the human control plane

The vault must work in Obsidian without requiring a plugin. V1 provides:

- a Home dashboard;
- Projects, Decisions, Lessons, and Handoffs navigation;
- a proposed-memory inbox;
- conflict and stale-memory views;
- templates and backlinks;
- optional Dataview enhancements that do not affect core operation.

A separate web UI is deferred until the core workflows prove that it is necessary.

## 8. Safety, maintenance, and deployment

- Default to local stdio MCP with no listening network port.
- Exclude credentials, auth state, tokens, `.env` files, and known secret paths from import.
- Use atomic writes and recoverable operations.
- Back up host configuration before every integration change.
- Provide a complete `disconnect` path.
- Keep the Python core dependency-light.
- Target Linux and macOS first; support Windows through WSL initially.
- Test installation and integration using isolated temporary home directories.
- Keep Git sync opt-in so private memory is never pushed silently.

## 9. Delivery milestones

### M0 — Repository foundation

Package structure, ADR process, memory schema, test strategy, and CI.

### M1 — Plaintext core

Vault, scopes, project identity, lifecycle operations, CLI, and full-text retrieval.

### M2 — Shared agent memory

MCP server, Codex and Claude Code connectors, and the three golden end-to-end scenarios.

### M3 — Migration

Claude, Codex, Markdown, and Obsidian import with preview, provenance, and deduplication.

### M4 — Human control

Obsidian navigation, review inbox, corrections, conflict handling, and stale-memory management.

### M5 — Distribution

pipx/uv installation, diagnostics, backup and recovery, versioned configuration migration, and user documentation.

### M6 — Scale layer

Optional local embeddings, hybrid retrieval, and knowledge-graph indexing without changing the canonical Markdown model.

## 10. V1 completion criteria

V1 is complete when a person can install Theatrum, connect Codex and Claude Code, save a durable fact with one agent, retrieve it with the other under the correct scope, inspect the exact Markdown source in Obsidian or a text editor, correct it with provenance intact, and recover or disconnect using ordinary local tools.

