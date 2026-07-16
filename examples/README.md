# Theatrum showcase demo

A single script that shows what Theatrum actually does: distill experience into
Markdown-with-frontmatter units, retrieve them under a token budget, keep hard
isolation between projects, and preserve provenance via `derived_from` links.

## What the demo shows

- **Experience units** — 9 memories (preferences, lessons, a decision, a
  synthesis, a project map) with real Problem / Tried / Worked / Takeaway
  content, not lorem ipsum.
- **Budgeted retrieval** — `theatrum context` returns a brief that fits under
  a token budget you name.
- **Hard project isolation** — searching a project's lesson at global scope
  returns *no matches*. A wrong match is worse than no match.
- **Provenance** — the synthesis links to the memories it was derived from,
  which Obsidian renders as edges in the graph.

## Run it

```sh
bash examples/demo.sh                       # ephemeral, cleaned up on exit
KEEP=1 bash examples/demo.sh                # keep the throwaway vault
SNAPSHOT=1 bash examples/demo.sh            # also refresh examples/demo-vault/
THEATRUM_BIN=./bin/theatrum bash examples/demo.sh
```

## See the graph

Open `examples/demo-vault/` as an Obsidian vault. It opens straight into the
graph view; the synthesis node and the project map sit at the centre of the
webapp cluster, with `derived_from` and `[[wikilink]]` edges drawn between them.

> `demo-vault/` is generated output. Edit `demo.sh`, not the snapshot.
