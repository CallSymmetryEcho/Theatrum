# Theatrum

> **One memory palace. Every agent.**

Theatrum is a local-first memory control plane for AI agents.

Today, Codex, Claude Code, and other agents remember in separate silos. Theatrum gives them one user-owned place to preserve durable knowledge, retrieve the right context, and hand work across agent boundaries.

## The idea

- **Plain text is the source of truth.** Memories remain readable, editable, diffable Markdown.
- **Memories are distilled experience, not notes.** Each unit captures the problem, what was tried, what worked, and the takeaway — the vault grows into a second brain.
- **Retrieval is the product.** `memory_context` returns a map plus the most relevant experience under the caller's token budget.
- **The user owns the palace.** The default store lives locally and can be opened directly as an Obsidian vault.
- **Agents share without collapsing scopes.** Global, project, agent, and handoff memory stay explicit.
- **Git is the audit trail.** History, review, rollback, and optional sync use familiar tools.
- **Indexes are disposable.** Keyword, graph, and future vector indexes are derived from the vault and can always be rebuilt.
- **Integrations are adapters.** Codex, Claude Code, and future agents connect through stable interfaces such as MCP, without making vendor-private databases canonical.

The project is intentionally starting with a small, dependable core. Semantic retrieval and large-scale vector storage can be added later without changing who owns the memory or how it is audited.

Read the [Project Anchor](docs/PROJECT_ANCHOR.md) for the boundaries that guide the design.

## Status

Theatrum is at the architecture and MVP-definition stage.

