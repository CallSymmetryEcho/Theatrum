#!/usr/bin/env bash
# Theatrum 5-minute demo — builds a throwaway vault, saves distilled experience,
# retrieves it under a token budget. Optionally snapshots the vault into the
# repo so Obsidian can render the knowledge graph.
#
# Usage:
#   bash examples/demo.sh              # ephemeral vault, cleaned up on exit
#   KEEP=1 bash examples/demo.sh       # keep the throwaway vault for inspection
#   SNAPSHOT=1 bash examples/demo.sh   # also refresh examples/demo-vault/
#   THEATRUM_BIN=/path/to/theatrum ... # override the theatrum entrypoint

set -euo pipefail

THEATRUM="${THEATRUM_BIN:-theatrum}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SNAP_DIR="$HERE/demo-vault"

THEATRUM_HOME="$(mktemp -d -t theatrum-demo.XXXXXX)"
export THEATRUM_HOME

cleanup() {
  if [ "${KEEP:-0}" = "1" ]; then
    echo "-- kept vault at $THEATRUM_HOME"
  else
    rm -rf "$THEATRUM_HOME"
  fi
}
trap cleanup EXIT

banner() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
note()   { printf '\033[0;90m%s\033[0m\n' "$*"; }

banner "init"
"$THEATRUM" init

WEBAPP="github.com/acme/webapp"
MOBILE="github.com/acme/mobile"

banner "remember: 9 distilled experience units"

id1=$("$THEATRUM" remember "Prefer uv over pip; never install into system Python.

Problem: pip mutates the system interpreter and leaks between projects.
Tried: pip with --user (still global-ish; PATH ordering surprises).
Worked: uv creates a fast, isolated venv per project; lockfile is reproducible.
Takeaway: reach for uv first; pip only inside an already-activated venv." \
  --type preference --scope global \
  --title "Prefer uv over pip" \
  --tags python,tooling | awk '{print $2}')

id2=$("$THEATRUM" remember "跟用户沟通一律用中文；代码注释、commit message、日志用英文。

原因：用户母语是中文，交流更顺畅；代码要给全球协作者读，英文是最小公倍数。
反例：把中文注释嵌进源码，非中文同事一脸问号。
结论：对人说中文，对机器说英文。" \
  --type preference --scope global \
  --title "沟通用中文，代码用英文" \
  --tags language,style | awk '{print $2}')

id3=$("$THEATRUM" remember "Use FTS5 trigram tokenizer for CJK search; do not rely on jieba.

Problem: default FTS5 unicode61 tokenizer splits Chinese text on whitespace, so 中文搜索 indexes as one opaque token and single-character queries miss.
Tried: jieba word segmentation — extra dep, model files, and non-deterministic across versions.
Worked: FTS5 built-in trigram tokenizer indexes every 3-char window; recall on 2-3 char queries jumps from ~0% to usable, zero extra deps.
Takeaway: for CJK full-text search, trigram beats word-segmentation when your dependency budget is tight." \
  --type lesson --scope project --project "$WEBAPP" \
  --title "FTS5 trigram vs jieba for CJK" \
  --tags fts5,cjk,search | awk '{print $2}')

id4=$("$THEATRUM" remember "Postgres connection pool exhaustion under gunicorn was a leak, not a sizing issue.

Problem: p99 latency climbed to timeout after ~10 minutes of load; pool showed 0 idle.
Tried: bumped pool from 10 to 40 → bought 20 minutes, then the same wall. Masked the leak.
Worked: audited every request path; a streaming SSE endpoint held a connection open across yields and never called conn.close() on client disconnect. Wrapped it in a try/finally that returns the conn to the pool on GeneratorExit.
Takeaway: if raising the pool only delays the crash, the pool is not the problem — find the connection that never comes home." \
  --type lesson --scope project --project "$WEBAPP" \
  --title "Postgres pool exhaustion was a leak" \
  --tags postgres,gunicorn,performance | awk '{print $2}')

id5=$("$THEATRUM" remember "Flaky CI test was a timezone-naive datetime comparison, not test order.

Problem: test_report_window_boundary passed locally, failed in CI ~1 in 4 runs.
Tried: rerun on failure (green-washing), pytest-randomly to rule out ordering — irrelevant.
Worked: the fixture built 'now' with datetime.utcnow() (naive) and compared against a timezone-aware value from the DB. Depending on CI runner clock skew vs UTC, the boundary flipped. Fix: freeze time with a tz-aware fixture (freezegun with tz='UTC') and ban datetime.utcnow() via ruff DTZ003.
Takeaway: 'flaky' usually means 'depends on wall-clock or timezone'. Freeze time, then assert." \
  --type solution --scope project --project "$WEBAPP" \
  --title "Flaky test = tz-naive datetime" \
  --tags testing,ci,datetime | awk '{print $2}')

id6=$("$THEATRUM" remember "Chose argparse over click for the CLI shipped via pipx.

Problem: click is ergonomic but adds a top-level dependency and ~200KB to a tool users install globally.
Tried: click for the first cut — nested Groups read nicely, but the dep pulled in colorama on Windows and slowed cold start by ~40ms.
Worked: rewrote in stdlib argparse. Subparsers cover everything we need; help text is uglier but functional. Cold start dropped, dep tree shrank to 2 runtime deps.
Takeaway: for a CLI you want everyone to 'pipx install' without thinking, dependency budget beats ergonomics." \
  --type decision --scope project --project "$WEBAPP" \
  --title "argparse over click" \
  --tags cli,dependencies | awk '{print $2}')

id7=$("$THEATRUM" remember "Gradle build cache corruption after force-quit produces silent stale-class bugs.

Problem: after a hard OS shutdown mid-build, the app ran fine but a rebuilt screen used code from two commits ago.
Tried: ./gradlew clean — did not touch ~/.gradle/caches; the poisoned entries survived.
Worked: rm -rf ~/.gradle/caches/build-cache-* and .gradle/ inside the project, then rebuild. Also enabled org.gradle.caching.debug=true in CI to catch cache-key collisions early.
Takeaway: 'clean' is project-local; the real cache lives in \$HOME. When behavior contradicts source, nuke the shared cache before you debug the code." \
  --type lesson --scope project --project "$MOBILE" \
  --title "Gradle cache corruption" \
  --tags gradle,android,build | awk '{print $2}')

id8=$("$THEATRUM" remember "Debugging production webapp issues: three hard-won rules.

Rule 1 — When raising a limit only delays the crash, you have a leak, not a sizing issue. See [[$id4]].
Rule 2 — 'Flaky' is code for 'depends on wall-clock or timezone'. Freeze time before you assert. See [[$id5]].
Rule 3 — When your search recall is near zero on short queries, the tokenizer is wrong, not the ranking. See [[$id3]].

Together these say: before tuning, verify the axis you are tuning is the one that matters. Otherwise you buy time and lose signal.

## Derived from
- [[$id3]]
- [[$id4]]
- [[$id5]]" \
  --type synthesis --scope project --project "$WEBAPP" \
  --title "Three rules for debugging the webapp" \
  --derived-from "$id3,$id4,$id5" \
  --tags debugging,principles | awk '{print $2}')

id9=$("$THEATRUM" remember "Map of the webapp project memories.

Coverage today: CJK search tokenizer choice, Postgres pool discipline, CI datetime hygiene, and the CLI dependency-budget decision. The cross-cutting synthesis lives at [[$id8]] and is the entry point when a production issue looks familiar.

Gaps: no memories yet on deploy rollback, on-call runbook, or auth session invalidation." \
  --type project-summary --scope project --project "$WEBAPP" \
  --title "webapp project map" \
  --tags map,index | awk '{print $2}')

echo
note "saved: $id1  $id2  $id3  $id4  $id5  $id6  $id7  $id8  $id9"

banner "recall: CJK search inside the webapp project"
"$THEATRUM" recall "CJK search tokenizer" --scope project --project "$WEBAPP"

banner "recall: 'connection pool' at global scope only"
note "Hard isolation: the webapp lesson is in projects/, not global/. A wrong project"
note "match is worse than no match, so Theatrum returns 'no matches' rather than guess."
"$THEATRUM" recall "connection pool" --scope global

banner "context: budgeted brief for a production outage"
"$THEATRUM" context "debugging a production webapp outage" \
  --project "$WEBAPP" --budget 1200

if [ "${SNAPSHOT:-0}" = "1" ]; then
  banner "snapshot: refresh $SNAP_DIR"
  mkdir -p "$SNAP_DIR"
  # Clear only the generated content; preserve the pre-baked .obsidian/ config.
  rm -rf "$SNAP_DIR/global" "$SNAP_DIR/projects" "$SNAP_DIR/inbox" "$SNAP_DIR/MAP.md"
  for name in global projects inbox MAP.md; do
    src="$THEATRUM_HOME/vault/$name"
    if [ -e "$src" ]; then
      cp -R "$src" "$SNAP_DIR/"
    fi
  done
  echo "wrote snapshot → $SNAP_DIR"
fi

banner "done"
echo "vault: $THEATRUM_HOME/vault"
if [ -d "$SNAP_DIR" ]; then
  echo "open examples/demo-vault in Obsidian to see the knowledge graph"
fi
