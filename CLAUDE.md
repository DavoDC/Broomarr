# Broomarr - working notes

Public repo. Nothing personal goes in here: no real profile names, no real show titles, no household context, no paths outside this repo. `config/config.json` holds the live credentials and is gitignored - never commit it, never quote its contents in a commit message, an issue or a doc.

## Invariants

**Broomarr never deletes.** No `--delete` flag, no write call to any API, no filesystem access. If a request would add one, say no and explain why - `docs/DESIGN.md` has the argument. This is the property the whole safety case rests on.

**An unknown value blocks.** Every branch in `verdict()` that cannot establish a fact must append a reason. Adding a code path where a failure results in a pass is the one defect class that matters here. Skip-on-unknown is what made the predecessor tool unsafe.

**Never decide from a count.** `episodeCount` and `episodeFileCount` both exclude unmonitored episodes, so they can agree while a whole season is missing. Enumerate `/api/v3/episode` and check each episode. Do not filter missing episodes by `monitored` - that reintroduces exactly the hidden filter the enumeration exists to defeat.

## Commands

```
python -m pytest tests -q          run the suite
python src/broomarr.py --all       scan the library (needs live Sonarr + Tautulli)
python src/broomarr.py "Title"     explain one show
```

## Layout

`src/broomarr.py` is the whole tool - standard library only, no dependencies, Python 3.8+. `Library` takes an injectable `fetch` and `now` so the decision logic is testable without live services; tests never hit the network. `tests/test_verdict.py` is mostly deletions that must not happen. New safety behaviour gets a test first.
