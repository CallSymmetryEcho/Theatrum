# Theatrum Project Anchor

## Problem

AI coding agents accumulate useful preferences, decisions, lessons, and project context, but each product stores them differently. Knowledge becomes fragmented, difficult to inspect, hard to transfer, and easy to lose.

## Thesis

A personal memory system for agents should begin as a transparent knowledge repository, not as an opaque model feature or vector database. Every agent should be able to use it, while the human remains the final owner and editor.

## Non-negotiable principles

1. **Local-first:** useful without an account, hosted service, or model API.
2. **Human-readable:** canonical memories are files a person can understand and edit.
3. **Vendor-neutral:** no agent's private database or session format becomes the core schema.
4. **Scoped by design:** global preferences never silently become project facts, and one project's context never leaks into another.
5. **Source-backed:** memories carry provenance, timestamps, and confidence instead of presenting guesses as facts.
6. **Auditable and reversible:** changes can be reviewed, diffed, corrected, and rolled back.
7. **Progressively enhanced:** search starts with files and metadata; vector and graph retrieval remain optional derived layers.
8. **Low-friction:** installation, agent connection, backup, and recovery should be understandable by an individual user.

## Initial product boundary

The first useful release will provide:

- one user-level vault, defaulting to `~/.theatrum/vault`;
- explicit global, project, agent, decision, lesson, and handoff scopes;
- a small CLI for setup, capture, recall, inspection, import, and health checks;
- a local MCP server for shared access from Codex and Claude Code;
- read-only importers for existing agent memories;
- Obsidian compatibility without requiring Obsidian;
- Git-friendly storage and deterministic rebuildable indexes.

The first release will not ingest every conversation automatically, rewrite vendor-owned state, require embeddings, or attempt autonomous memory consolidation without review.

## Success condition

A person can install Theatrum, connect two different agents, save a durable fact with one, retrieve it with the other in the correct scope, inspect the exact Markdown source, and undo the change using ordinary local tools.

