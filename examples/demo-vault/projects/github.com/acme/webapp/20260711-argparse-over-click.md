---
id: 20260711-argparse-over-click
type: decision
scope: project
project: github.com/acme/webapp
tags:
- cli
- dependencies
created: '2026-07-11'
source: user_requested
status: active
confidence: medium
derived_from: []
superseded_by: null
used: 0
dead_end: 0
title: argparse over click
---
Chose argparse over click for the CLI shipped via pipx.

Problem: click is ergonomic but adds a top-level dependency and ~200KB to a tool users install globally.
Tried: click for the first cut — nested Groups read nicely, but the dep pulled in colorama on Windows and slowed cold start by ~40ms.
Worked: rewrote in stdlib argparse. Subparsers cover everything we need; help text is uglier but functional. Cold start dropped, dep tree shrank to 2 runtime deps.
Takeaway: for a CLI you want everyone to 'pipx install' without thinking, dependency budget beats ergonomics.
