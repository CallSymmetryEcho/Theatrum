---
id: 20260711-prefer-uv-over-pip
type: preference
scope: global
project: null
tags:
- python
- tooling
created: '2026-07-11'
source: user_requested
status: active
confidence: medium
derived_from: []
superseded_by: null
used: 0
dead_end: 0
title: Prefer uv over pip
---
Prefer uv over pip; never install into system Python.

Problem: pip mutates the system interpreter and leaks between projects.
Tried: pip with --user (still global-ish; PATH ordering surprises).
Worked: uv creates a fast, isolated venv per project; lockfile is reproducible.
Takeaway: reach for uv first; pip only inside an already-activated venv.
