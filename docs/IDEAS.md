# Ideas & Future Work

Single source of truth for all pending work in this repo. Settled decisions and completed features -> `docs/HISTORY.md`.

---

## Current Focus

Broomarr has never been run against a live Sonarr or Tautulli. Everything in Tier 1 is a correctness or first-run blocker and comes before movie support.

---

## Pending - Main Work

*(Ordered by priority. Quick wins go FIRST within each tier - small, unblocked items before large/blocked ones. Items that are blocked or depend on other items go below their prerequisite.)*

---

### Tier 1 - BLOCKING (correctness, before the tool is run at all)

**The watched-vs-on-disk join is not implemented.** This is the tool's central claim and it does not happen. `verdict()` compares `seen = len(users[watcher]["eps"])` against `on_disk = stats["episodeFileCount"]` - two counts. It never compares which episodes were watched against which episodes exist. Verified by probe: watcher watched S01E01-E10, on disk are S01E01-E07 plus S02E01-E03 (three episodes nobody has ever watched), counts both read 10, series ended, quiet period cleared - `verdict(..., deep=True)` returns `(True, [])`, safe to delete. Two compounding faults: the identities are discarded, and `episodeFileCount` is itself the filtered count `docs/DESIGN.md` spends three paragraphs discrediting. The fix is a set difference over `(season, episode)` identifiers sourced from the enumerated episode list, which `episode_facts()` already walks - no extra API call. Delete `episodeFileCount` from the strict path entirely.

---

**Tests are written from the implementation, not from the specification.** All six README conditions have a test and all fifteen pass, so coverage reads as complete while the headline behaviour is absent. `test_partial_watch_blocks` only exercises the count branch with counts that genuinely differ (3 vs 6); nothing exercises equal counts with mismatched identities. Rewrite condition 2's tests against episode identifiers, and add the probe case above as a permanent regression fixture alongside the existing missing-first-season one. The lesson generalises: a test derived from the code can only ever confirm the code.

---

**The cheap prefilter's permissiveness is an unstated invariant with no test.** `scan()` runs `verdict(deep=False)` and only survivors get the strict check, so a show the prefilter blocks is never seen again. That is safe only while the prefilter is strictly weaker than the strict pass - if it ever blocks something the strict pass would have passed, a safe show is silently dropped (costs disk, not data, so it fails in the tolerable direction, but silently). Once the strict path gains the identifier join it becomes a strict superset, which should be asserted by a test rather than left as a comment.

---

### Tier 2 - BEFORE FIRST RUN (the tool has to be testable by hand)

**`scripts/run.bat` + `scripts/run.sh`, house style.** Standing preference across repos: RivalsVidMaker, FLAC_Flow, SBS_Download, StreamPilot and SpotifyPlaylistGen all have one. Needs the `--no-pause` two-mode contract, start/end timing, and a window that does not close on completion. Should offer both modes (scan-all, explain-one) rather than hardcoding one.

---

**First-run legibility.** The tool's only output is a list a human acts on, which makes legibility a safety property rather than a nicety. Current gaps: bare `python src/broomarr.py` prints the module docstring and returns 1 (usable but accidental); there is no `--help`; a wrong `watcher` name produces "no watch history for this show" on every single show with no hint that the name is the problem; an unreachable Sonarr or Tautulli surfaces as a raw `urllib` traceback from inside a scan rather than a clear message; and there is no way to check a config is correct short of scanning the whole library. A `--check` that verifies both services respond and reports whether the configured watcher matches a real Tautulli user would make the first run diagnosable.

---

**README rewrite: concise, no volatile content, conditions stated plainly.** Current README embeds a block of sample terminal output, which is guaranteed to drift the moment the CLI changes and is unverifiable by a reader. It also carries implementation detail (`episodeCount` field semantics) that belongs in `docs/DESIGN.md`, and setup detail that is fine but currently competes with the safety argument for the reader's attention. Rewrite so the README answers, in order: what it does, the six conditions in plain language, what it will never do, how to set it up. State explicitly that Broomarr is one decision with six ANDed conditions, not a configurable rule engine - that is a design property worth claiming, and it pre-empts "does it only support one rule?". No sample output, no counts, no screenshots.

---

**Docs routing.** Implementation detail and anything Claude needs -> `CLAUDE.md`. Design argument and the case against alternatives -> `docs/DESIGN.md`. README keeps only what a new reader needs. Currently the `episodeCount`/`episodeFileCount` explanation appears in all three.

---

### Tier 3 - HYGIENE

**Origin story belongs in the workspace, not the repo.** The concrete failure that prompted this tool involves household context and must never appear here. The repo is currently clean on this (grep over all tracked files found no personal names, family terms, real show titles or external paths), and `docs/DESIGN.md` already states the Maintainerr case generically. Keep it that way; the private background lives in the workspace.

---

## Lower Priority / Future

*(Ordered by size - smaller/quicker first. These are not urgent but worth doing eventually.)*

---

**Config validation for `sonarr_url` / `tautulli_url` reachability at startup.**
`load_config` currently only checks that the required keys are present, not
that the URLs are well-formed or reachable. A clear early error beats a
confusing stack trace from `urllib.request` deep inside a scan. Largely
subsumed by the `--check` mode above if that is built first.

---

**Multiple watchers per show, not one named watcher.** `config.json` currently
takes a single `watcher` string matched case-insensitively. Households where
more than one person needs to have finished a show before it is safe to
remove would need the verdict to require all configured watchers, not just
one - matters for shared libraries, not solo ones.

---

**Movie support via Radarr.** Radarr has no
episode concept, so the join is simpler than the Sonarr side: one film either
has a file or does not, and Tautulli's `media_type=movie` history gives a
single watched/not-watched fact per user instead of a per-episode set. The
"unknown blocks" rule and the read-only invariant both carry over unchanged -
a movie verdict is just a smaller version of `Library.verdict()`. Deliberately
demoted below the Tier 1 items: extending a decision engine whose core join is
absent would copy the fault into a second media type.

---

## See Also

- `docs/HISTORY.md` - completed features, settled design decisions, parked ideas
