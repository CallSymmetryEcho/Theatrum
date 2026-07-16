---
id: 20260711-flaky-test-tz-naive-datetime
type: solution
scope: project
project: github.com/acme/webapp
tags:
- testing
- ci
- datetime
created: '2026-07-11'
source: user_requested
status: active
confidence: medium
derived_from: []
superseded_by: null
used: 0
dead_end: 0
title: Flaky test = tz-naive datetime
---
Flaky CI test was a timezone-naive datetime comparison, not test order.

Problem: test_report_window_boundary passed locally, failed in CI ~1 in 4 runs.
Tried: rerun on failure (green-washing), pytest-randomly to rule out ordering — irrelevant.
Worked: the fixture built 'now' with datetime.utcnow() (naive) and compared against a timezone-aware value from the DB. Depending on CI runner clock skew vs UTC, the boundary flipped. Fix: freeze time with a tz-aware fixture (freezegun with tz='UTC') and ban datetime.utcnow() via ruff DTZ003.
Takeaway: 'flaky' usually means 'depends on wall-clock or timezone'. Freeze time, then assert.
