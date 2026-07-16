---
id: 20260711-three-rules-for-debugging-the-webapp
type: synthesis
scope: project
project: github.com/acme/webapp
tags:
- debugging
- principles
created: '2026-07-11'
source: user_requested
status: active
confidence: medium
derived_from:
- 20260711-fts5-trigram-vs-jieba-for-cjk
- 20260711-postgres-pool-exhaustion-was-a-leak
- 20260711-flaky-test-tz-naive-datetime
superseded_by: null
used: 0
dead_end: 0
title: Three rules for debugging the webapp
---
Debugging production webapp issues: three hard-won rules.

Rule 1 — When raising a limit only delays the crash, you have a leak, not a sizing issue. See [[20260711-postgres-pool-exhaustion-was-a-leak]].
Rule 2 — 'Flaky' is code for 'depends on wall-clock or timezone'. Freeze time before you assert. See [[20260711-flaky-test-tz-naive-datetime]].
Rule 3 — When your search recall is near zero on short queries, the tokenizer is wrong, not the ranking. See [[20260711-fts5-trigram-vs-jieba-for-cjk]].

Together these say: before tuning, verify the axis you are tuning is the one that matters. Otherwise you buy time and lose signal.

## Derived from
- [[20260711-fts5-trigram-vs-jieba-for-cjk]]
- [[20260711-postgres-pool-exhaustion-was-a-leak]]
- [[20260711-flaky-test-tz-naive-datetime]]
