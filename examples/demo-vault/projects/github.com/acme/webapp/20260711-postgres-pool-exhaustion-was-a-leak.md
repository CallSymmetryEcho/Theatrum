---
id: 20260711-postgres-pool-exhaustion-was-a-leak
type: lesson
scope: project
project: github.com/acme/webapp
tags:
- postgres
- gunicorn
- performance
created: '2026-07-11'
source: user_requested
status: active
confidence: medium
derived_from: []
superseded_by: null
used: 0
dead_end: 0
title: Postgres pool exhaustion was a leak
---
Postgres connection pool exhaustion under gunicorn was a leak, not a sizing issue.

Problem: p99 latency climbed to timeout after ~10 minutes of load; pool showed 0 idle.
Tried: bumped pool from 10 to 40 → bought 20 minutes, then the same wall. Masked the leak.
Worked: audited every request path; a streaming SSE endpoint held a connection open across yields and never called conn.close() on client disconnect. Wrapped it in a try/finally that returns the conn to the pool on GeneratorExit.
Takeaway: if raising the pool only delays the crash, the pool is not the problem — find the connection that never comes home.
