# History

---

## 2026-09-14 - Movie support: Radarr joins Sonarr and Tautulli

Second step of the build brief in `docs/design/build-brief.md`, following the
empty-versus-unreadable fix. Added `MovieLibrary` alongside `Library`, both
now built on a shared `_ServiceClient` base so the Tautulli client and the
`matches_watcher()` rule exist exactly once instead of twice. `matches_watcher()`
itself moved to a module-level function for the same reason.

The movie join is two-part - `_movie_key()` returns `(title.lower(), year)`,
never title alone, because two different films can share a title the way two
different shows rarely do in one library. A row or Radarr entry whose year
will not coerce to `int` is skipped rather than joined to the wrong film. Two
Radarr entries that share a `(title, year)` key are both flagged and both
block, since the join cannot tell them apart - `_duplicate_keys()` computes
this from the same cached bulk movie list `movie_facts()` and `verdict()`
also use, so a scan does not re-fetch Radarr per movie.

The one design point worth stating: a partial Tautulli view is the *entire*
watch signal for a movie, where on the TV side it is harmless because the set
difference still names the specific unwatched episodes. `movie_watch_index()`
therefore tracks "started but never finished" as its own state
(`watched_status < 0.5`) rather than folding it into "no history at all" -
`verdict()` gives it a distinct reason so a partially-watched film is never
mistaken for one nobody touched.

`load_config()` now treats `radarr_url`/`radarr_api_key` as an optional pair:
either both are set or neither is, since one without the other would look
configured and silently never scan movies. `--movies` scans movies alone;
`--all` scans TV and, if Radarr is configured, movies too; `--check` verifies
Radarr the same way it verifies Sonarr and Tautulli, only when configured.
`tests/test_movie_verdict.py` covers the join, the duplicate-key case, the
partial-view case, an unreachable Radarr (blocks, does not skip), and the
`movie_facts()` "missing id returns None, not an empty MovieFacts" contract.

Radarr is not configured in this environment's live `config/config.json`, so
`--check`/`--movies` against a real Radarr instance could not be hand-verified
here - only the injected-fetch unit tests in `tests/test_movie_verdict.py`
confirm this side, same pattern as the rest of the suite.

## 2026-09-14 - The empty-versus-unreadable collapse fixed on the TV side

Fixed the fail-open `docs/design/reclaim-backend-design.md` section 2 diagnosed:
a literal `[]` from Sonarr's `/api/v3/episode` made `episode_facts()` return
`([], [], set())` without raising, so `verdict()`'s three downstream checks
(missing, upcoming, unwatched) were all falsy and a show read as safe on the
strength of a response that established nothing. Three independent changes,
any one of which alone would have prevented it: `episode_facts()` now raises
a new `UnreadableFacts` when the response is `None`, not a list, or an empty
list, each with its own message; `verdict()`'s deep branch explicitly checks
`on_disk_eps is None` (belt-and-braces - not reachable today, but the contract
stays self-documenting) separately from an empty-but-established
`on_disk_eps`, which now also blocks with "no episodes with files found on
disk, nothing to verify against"; and `explain()` and
`dry_run_report.evaluate()` were both updated for the same `None` case.
Landed first, ahead of movie support and the reclaim path, because the same
pass attaches a delete button to `verdict()`'s output and shipping that over
a known fail-open in the function feeding it would have been indefensible.

---

## 2026-09-14 - Source-level audit of the landscape: the "only tool that asks Sonarr" claim was false

The re-scan below was written from README and documentation claims. This pass
cloned the seven credible candidates (Maintainerr, reaper, Reclaimerr, PrunArr,
Deleterr, Purgeomatic, OCDarr) into `NOT_MY_REPOS/`, read the actual
watched-status and deletion logic, resolved every "Not stated" cell, and then
re-audited that enrichment against the clones a second time. Findings and the
revised reasoning are in `docs/ALTERNATIVES.md`.

**The correction that mattered: two other tools already read Sonarr's episode
list as ground truth.** reaper's `_final_episodes()` builds its denominator from
Sonarr's `/episode` response on `hasFile` and its docstring rejects
`episodeCount` and `totalEpisodeCount` by name, for the same reasons
`docs/References/DevContext.md` gives. Reclaimerr uses
`season.sonarr_episode_numbers` as the denominator, commented "Sonarr's
canonical episode inventory is the denominator." The verdict below asserted
that no project does this. It was wrong, and the enrichment pass had already
gathered the evidence without noticing it contradicted the conclusion sitting
beside it.

What survives is narrower: Broomarr's differentiator is the **set difference**,
not the fact that it asks Sonarr. reaper compares two high-water marks (highest
watched vs highest on disk) and catches mid-season gaps with a separate,
operator-disableable `protect_incomplete` gate; Reclaimerr matches per episode
number then reduces to counts at the boundary. Broomarr names the survivors of
`on_disk_eps - watched_eps`. One increment stronger than the field, not a
different category.

**Deleterr is genuinely unsafe** and is now named as such:
`find_watched_data()` returns `None` indistinguishably for an unreachable
Tautulli, an empty activity set, a failed GUID match, and a show nobody
watched, so an empty fetch makes a whole library deletable under a common
configuration. Skip-on-unknown in its purest form.

**The "Auto-deletes?" column was replaced** with "Wrong-call cost (reversal
window)." The old column scored Purgeomatic (cron, whole-series delete on one
aggregate timestamp, no undo) and reaper (dry-run default, off until armed,
canary delete, arm re-read per item, grace countdown) identically at "Yes,"
which hid the only difference that matters. Reasoning in `docs/ALTERNATIVES.md`.

**Verdict: keep building Broomarr - but the reasons are now practical, not
architectural.** AGPL-3.0 vs MIT; reaper's rigour is inseparable from its stack
(database, 31 migrations, scan pipeline, React front end) so there is nothing
to harvest piecemeal; and the two tools solve different-sized problems. reaper
is the first tool in this survey not disqualified on the merits, and the open
action is to run it in dry-run mode against the real library before the next
planning round. Opened as a backlog item, along with opt-in auto-delete as a
future option - see `docs/IDEAS.md`. `CLAUDE.md` and `README.md` invariants
unchanged: Broomarr does not delete today.

## 2026-09-14 - Competitive landscape re-scan: keep building

Before movie support, the GUI, or anything else got more investment, checked
whether some other project already does Broomarr's job well enough to fork
or adopt instead. `docs/References/DevContext.md` only ever documented one
comparison in depth (Maintainerr, tried and retired 2026-07-26) - nothing in
this repo or the workspace had checked PrunArr, Reclaimerr, Janitorr,
Cleanuparr, or any other similarly-named *arr-adjacent cleanup tool.

Researched about a dozen comparable and adjacent tools (Maintainerr, reaper,
Reclaimerr, PrunArr, Deleterr, Purgeomatic, OCDarr, Plexorcist,
sonarr-plex-cleaner, Prunerr, Plex-Cleaner, Usharr, Cleanarr) plus five
ruled-out-on-purpose near misses that turned out to solve a different
problem (Janitorr - not watch-status-driven; Cleanuparr - a download-queue
cleaner, not a library one, despite the name collision with PrunArr;
Sortarr - read-only; Watcharr/Wizarr/Recyclarr - unrelated domains).
Full comparison table and reasoning in `docs/ALTERNATIVES.md`.

**Verdict: keep building.** No project found confirms both of Broomarr's
load-bearing invariants at once - true Sonarr-side per-episode enumeration
(most ask the media server instead, the exact gap this repo exists to
close) and never auto-deleting (almost everything else does, after a grace
period). `reaper` (scythe-labs) is the closest philosophical match - an
explicit, type-enforced "unknown never condemns" principle and deletion
off-by-default - but it's pre-release and doesn't confirm per-episode
enumeration either way. Worth revisiting if it ships a tagged release.

## 2026-08-21 - First real hand-run, and a reviewable dry-run report

Confirmed by reading the source, not the README, that Broomarr already had
no unreviewed-execution mode to build a dry run against: `broomarr.py` has
no `--delete` flag, no write call to any API (every `fetch()` call is a
plain `urllib` GET, dispatched through `http_get` with no `data` argument),
and no filesystem access outside reading `config.json`. There was nothing
to make safe that was not already safe - the whole tool already is the dry
run.

What was missing was a report a human could actually judge a call from.
`scan()`'s SAFE TO DELETE section printed a title and a size only - a
verdict with the evidence stripped out. Added `src/dry_run_report.py`,
which reuses `Library.verdict()` and `Library.episode_facts()` unchanged
(it computes no safety decision of its own - tests assert the safe/blocked
split and every reason string come straight from `verdict()`) and adds the
evidence scan() already computes internally but never prints: who matched
as watcher, last-watched date, the quiet-period margin, episode counts, and
the specific missing/unwatched/upcoming episode identifiers. Sorts so the
closest calls lead: SAFE TO DELETE puts a show that only just cleared the
quiet period first regardless of size, then largest reclaim first; BLOCKED
puts the fewest-blocking-reasons shows first, since those are the ones
worth a second look, not the ones blocked six ways at once. Writes to
`captures/` (already gitignored), never Downloads. Tests first, per repo
convention - `tests/test_dry_run_report.py`, including an adversarial case
asserting a partially-watched show can never land in `safe_items`.

Ran `--check` then the new report against the real library (197 series,
Sonarr and Tautulli both live on localhost). 18 series survived the cheap
prefilter, 3 came back safe (53 GB across the three),
15 blocked, all on real evidence (unwatched episodes on disk, or aired
episodes never downloaded). Full report in `captures/dry-run-report-*.txt`
(gitignored, local only).

Adversarial read of `verdict()` and the join found one real, currently
dormant gap: the Sonarr-Tautulli join keys on lowercased title with no
`tvdbId` or rating-key cross-check, so two same-titled shows would merge
their watch history. Not triggered today (no duplicate titles in the
current library) but structural, not incidental - tracked in
`docs/IDEAS.md`. Also noted: `watch_index()` requests Tautulli history
with `length=50000` and no explicit sort order; today's library returns
2,108 rows (`recordsFiltered`) newest-first, so no truncation risk
currently exists, but if it ever did, the newest-first order means it
would drop the oldest rows rather than the most recent "last watched"
timestamp - the safe direction, not a bug, but worth a comment in code if
the library grows enough to matter.

## 2026-07-26 - First-run legibility: --check, --help, and a watcher-mismatch warning

The tool's only output is a list a human acts on, which makes legibility a safety
property rather than a nicety. Four traps closed before the first real run.

The worst was silent: a `watcher` value in `config.json` that matches no Tautulli
friendly name makes every show block with "no watch history for this show", so the
scan reports nothing safe to delete and looks exactly like a genuinely clean library.
`scan()` now collects the friendly names actually present and warns up front, naming
what was configured and what exists. The matching rule moved into
`Library.matches_watcher()` so the warning and the verdict cannot drift apart - a
warning derived from a second copy of the rule would eventually lie.

Service failures no longer escape as a raw `urllib` traceback from the middle of a
scan; `sonarr()` and `tautulli()` wrap connection, body and response-shape failures
into a message naming the service and the configured base URL. The base URL is used
deliberately rather than the request URL, because Tautulli's API key travels in the
query string. `verdict()`'s per-series handler is unchanged and still turns these into
a blocking reason rather than a fatal error - unknown blocks.

Added `--check`, which confirms both services respond and whether the watcher matches,
with no per-episode calls, and `--help`, so that bare invocation no longer relies on
printing the module docstring by accident.

## 2026-07-26 - README rewrite: state the conditions, not sample output

Commit `6c0471a`. Dropped the block of example terminal output from the README - it
goes stale the moment the CLI's output changes shape, nothing tests it against
reality, and a reader has no way to check it either way. Replaced it with the six
conditions in plain language, laid out as a table, and a direct answer to "is this a
rule engine" (no, and why not). Field-level implementation detail that used to live in
the README moved out to `CLAUDE.md` instead, following the routing split: README is
what a new reader needs to decide whether to use the tool, `docs/References/DevContext.md` carries
the design argument, `CLAUDE.md` carries the implementation detail Claude needs when
touching the code.

## 2026-07-26 - scripts/run.bat launcher

Commit `0cf8668`. Windows entry point for people who would rather not type the
`python` invocations by hand. Prompts for scan-whole-library vs explain-one-show,
checks `config/config.json` exists first and prints the setup step if it does not
(instead of letting `broomarr.py` fail with a raw traceback), and keeps the window
open on completion (`cmd /k`) so the result is still on screen after the script
finishes. `--no-pause` skips the prompt (defaults to a full scan) and exits cleanly,
for anyone who wants to call it from something else.

## 2026-07-26 - Fixed: watched-vs-on-disk check compared counts, not identities

Commit `d52368d`. `verdict()` decided whether the watcher had seen everything on disk
by comparing `len(watched_eps)` to `stats["episodeFileCount"]` - two integers, never
which episodes they actually were. Equal counts with different identities read as
safe: a watcher who had seen S01E01 through E10 while S02E01 through E03 sat on disk
unwatched produced two equal numbers and a pass. `episodeFileCount` is also the count
`docs/References/DevContext.md` already argues against on separate grounds, so the one check whose
entire thesis is "never decide from a count" was itself deciding from one.

Fixed by having `episode_facts()` return the on-disk `(season, episode)` identifiers
as well as the missing/upcoming lists it already returned, and having `verdict()`
take a set difference against the watched set instead of comparing lengths. Both
sides are coerced to `int` first (`_to_int()`), because Tautulli returns these as
strings in some API versions and an uncoerced mismatch would silently join to
nothing, blocking every show rather than the wrong one - safe, but useless, and
indistinguishable from the check working. The shallow count-based fallback in the
cheap prefilter was deleted rather than patched: the prefilter is only safe because
it is structurally a weaker version of the strict check, the same function with the
episode-list conditions skipped, never an approximation of them. Regression tests
cover the count-agrees-but-identities-differ case and the prefilter-never-stricter
invariant. `docs/References/DevContext.md` gained a third trap section on why a count comparison is
unsafe even without a hidden filter involved.
