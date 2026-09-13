# Broomarr - working notes

**This repo is public on GitHub.** Nothing personal goes in here: no real profile names, no real show titles, no household context, no paths outside this repo. `config/config.json` holds the live credentials and is gitignored - never commit it, never quote its contents in a commit message, an issue or a doc.

Architecture rationale (why Sonarr not Plex, why Maintainerr was retired) lives in `docs/References/DevContext.md` - CLAUDE.md stays orientation-only.

## Invariants

**Nothing deletes without a human confirming it twice, days apart.** Deletion lives in `src/reclaim.py` and nowhere else. `src/broomarr.py` is still read-only: no `--delete` flag, no non-GET request, no filesystem access, and it never imports `reclaim`. The decision engine and the write engine are separate modules on purpose, because Maintainerr's third failing was that rule evaluation and deletion were one system.

**No schedule, no daemon, no timer ever reaches a delete call.** A flagged item sits in a hold queue for `hold_days`; the hold elapsing only makes it *offerable*, and a person must then confirm again, by typing, against a freshly recomputed verdict. If nobody opens the GUI, nothing is ever deleted. "An unrun script deletes nothing" still holds, and it is still why this is safe to rely on.

**Seven interlocks guard the execute path** (`src/reclaim.py`): scan freshness, hold elapsed, live re-verification, caps that abort rather than truncate, a canary delete of the smallest item first, a per-item re-read before each call, and a record written after each individual deletion rather than at the end of the run. Removing or weakening any of them is the change to refuse. `docs/design/reclaim-backend-design.md` section 4 states what each one protects against; an interlock whose purpose nobody can state is one somebody will delete as redundant.

**`verdict()` still cannot express "delete."** It returns candidates and reasons, exactly as before, and nothing downstream of it acts without a human. Every rule below about unknowns and counts applies unchanged, and matters more now than it did when the output was only ever printed.

**An unknown value blocks.** Every branch in `verdict()` that cannot establish a fact must append a reason. Adding a code path where a failure results in a pass is the one defect class that matters here. Skip-on-unknown is what made the predecessor tool unsafe. An empty or unreadable episode list blocks too - a literal `[]` from Sonarr is a failure to answer, not a series with no episodes, and `episode_facts()` raises `UnreadableFacts` on it rather than letting three falsy checks no-op into a pass.

**Never decide from a count.** `episodeCount` and `episodeFileCount` both exclude unmonitored episodes, so they can agree while a whole season is missing. Enumerate `/api/v3/episode` and check each episode. Do not filter missing episodes by `monitored` - that reintroduces exactly the hidden filter the enumeration exists to defeat. This invariant already lived here and was violated anyway: the count was in the watched-vs-on-disk check, not the missing-episodes check the invariant was written to guard, so nobody was watching for it there. The fix in `verdict()` is a set difference over `(season, episode)` int tuples - `on_disk_eps - users[watcher]["eps"]` - never a length comparison. Both sides go through `_to_int()` first; Tautulli returns season/episode as strings in some API versions, and an uncoerced mismatch would join to nothing and silently block every show instead of the right one. A history row whose season or episode will not coerce is skipped, not counted as watched. `episodeCount` and `episodeFileCount` must never appear inside `verdict()` at all - display-only, legitimate in `explain()` and `scan()`.

**The cheap prefilter must stay structurally weaker, never approximate.** `scan()` runs `verdict(deep=False)` over the whole library first; only survivors get the strict per-episode check. The cheap pass has to be the same function with the episode-list conditions skipped, not a different or approximate test - permissiveness has to be true by construction, because an approximation can disagree with the strict pass and silently drop a show it would have passed. Regression test: `tests/test_verdict.py::test_cheap_pass_never_blocks_what_the_strict_pass_would_examine`.

## Commands

```
python -m pytest tests -q          run the suite
python src/broomarr.py --all       scan the library (needs live Sonarr + Tautulli)
python src/broomarr.py "Title"     explain one show
python -m gui.main                 GUI, localhost only - scripts/run-gui.bat wraps this
```

## Layout

`src/broomarr.py` is the decision engine and `src/reclaim.py` is the write path: both standard library only, no dependencies, Python 3.8+, both unit-testable with an injectable `fetch` and `now` and no network. The CLI must keep working on a bare Python install with no `pip install` step, forever. `gui/` is the interactive interface and is the only part of the repo permitted a dependency (NiceGUI); it contains no safety logic, and `tests/test_no_gui_dependency.py` asserts that neither core module imports it.

`Library` (TV) and `MovieLibrary` (movies) both take an injectable `fetch` and `now`, and both build on a shared `_ServiceClient` base (Tautulli client, `matches_watcher()`) so the two sides cannot drift; tests never hit the network. The movie join is `_movie_key()` - `(title.lower(), year)`, never title alone - and two Radarr entries sharing a key both block, since `verdict()` cannot tell them apart. `tests/test_verdict.py` and `tests/test_movie_verdict.py` are mostly deletions that must not happen. New safety behaviour gets a test first.
