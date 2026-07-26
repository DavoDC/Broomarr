# Broomarr - working notes

Private on GitHub, written as though it were public - that is deliberate, so publishing stays a one-click decision rather than a cleanup project. Nothing personal goes in here: no real profile names, no real show titles, no household context, no paths outside this repo. `config/config.json` holds the live credentials and is gitignored - never commit it, never quote its contents in a commit message, an issue or a doc.

## Invariants

**Broomarr never deletes.** No `--delete` flag, no write call to any API, no filesystem access. If a request would add one, say no and explain why - `docs/DESIGN.md` has the argument. This is the property the whole safety case rests on.

**An unknown value blocks.** Every branch in `verdict()` that cannot establish a fact must append a reason. Adding a code path where a failure results in a pass is the one defect class that matters here. Skip-on-unknown is what made the predecessor tool unsafe.

**Never decide from a count.** `episodeCount` and `episodeFileCount` both exclude unmonitored episodes, so they can agree while a whole season is missing. Enumerate `/api/v3/episode` and check each episode. Do not filter missing episodes by `monitored` - that reintroduces exactly the hidden filter the enumeration exists to defeat. This invariant already lived here and was violated anyway: the count was in the watched-vs-on-disk check, not the missing-episodes check the invariant was written to guard, so nobody was watching for it there. The fix in `verdict()` is a set difference over `(season, episode)` int tuples - `on_disk_eps - users[watcher]["eps"]` - never a length comparison. Both sides go through `_to_int()` first; Tautulli returns season/episode as strings in some API versions, and an uncoerced mismatch would join to nothing and silently block every show instead of the right one. A history row whose season or episode will not coerce is skipped, not counted as watched. `episodeCount` and `episodeFileCount` must never appear inside `verdict()` at all - display-only, legitimate in `explain()` and `scan()`.

**The cheap prefilter must stay structurally weaker, never approximate.** `scan()` runs `verdict(deep=False)` over the whole library first; only survivors get the strict per-episode check. The cheap pass has to be the same function with the episode-list conditions skipped, not a different or approximate test - permissiveness has to be true by construction, because an approximation can disagree with the strict pass and silently drop a show it would have passed. Regression test: `tests/test_verdict.py::test_cheap_pass_never_blocks_what_the_strict_pass_would_examine`.

## Commands

```
python -m pytest tests -q          run the suite
python src/broomarr.py --all       scan the library (needs live Sonarr + Tautulli)
python src/broomarr.py "Title"     explain one show
```

## Layout

`src/broomarr.py` is the whole tool - standard library only, no dependencies, Python 3.8+. `Library` takes an injectable `fetch` and `now` so the decision logic is testable without live services; tests never hit the network. `tests/test_verdict.py` is mostly deletions that must not happen. New safety behaviour gets a test first.
