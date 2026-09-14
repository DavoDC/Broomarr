# History

---

## 2026-09-14 - Login-gated GUI: session auth, two roles, and the execute-path fixes it depended on

Built the auth/access-control plan `docs/IDEAS.md` had recorded in full
(Tailscale access for a friend, prerequisites before giving it out) as a
straight implementation pass, since the plan already worked out the design
in detail; nothing here revisits the plan's reasoning, only what shipped
against it.

New `gui/auth.py`: `hash_password()`/`verify_password()` on
`hashlib.pbkdf2_hmac` and `hmac.compare_digest`, `check_credentials()`
reading a `gui_users` config block (name -> password hash plus
`"admin"`/`"viewer"` role), `current_user()`/`log_in()`/`log_out()` on
`app.storage.user`, and a `RequireLoginMiddleware` allowlisting only
`/login` and NiceGUI's own static/internal paths. `is_admin()`/
`require_admin()` fail open to admin when `gui_users` is empty (no accounts
configured means the login gate never engaged, matching today's no-auth
behaviour on David's own machine) and fail closed to the session's real
role once any account exists. `require_admin()` is called inside the
handlers themselves - `on_flag()`, both cancel closures, `do_execute()` -
not only by omitting buttons from a viewer's rendered page, per the plan's
own reasoning that the markup and the enforcement must not be the same
check. `username_for_record()` feeds the acting account into
removal-history records.

`gui/config.py` reads `gui_host`/`gui_port` from config (defaulting to
`"127.0.0.1"`/`8472`) in place of the old hardcoded port constant, and
`config/config.example.json` documents `gui_users`, `gui_storage_secret`,
`gui_host`, `gui_port` with placeholders, plus a comment that leaving
`gui_users` empty keeps the GUI exactly as it always behaved.
`scripts/set-gui-password.py` prints a hash for pasting so a plaintext
password is never typed into the config file, and
`scripts/check-auth-enforced.py` sends unauthenticated requests at every
route including NiceGUI's internal endpoints and asserts a redirect or 401
from all of them - the negative test the plan called for, meant to run
before any tailnet grant exists. `tests/test_gui_auth.py` covers hashing,
credential checks, role gating with auth on and off, and `require_admin()`
raising for a viewer session.

Two findings from the pre-ship audit turned out to be the same work as
steps in this plan and were fixed alongside it, not separately: the
execute path now has a re-entrancy guard (`_execute_lock`, non-blocking
`acquire()` before `do_execute()` runs) and every long-running handler
(`do_rescan()`, `do_check()`, `do_execute()`) offloads to
`nicegui_run.io_bound()` with a `"loading"` prop on its button for the
duration, so a second click while a scan is running no longer queues a
second run or freezes the page for other connected sessions. The
typed-`REMOVE` confirm gained a persistent visible label (was a placeholder
that vanished on the first keystroke), `.strip()`-tolerant matching, and an
explicit "type REMOVE exactly" message on a mismatch instead of a button
that just stayed disabled. Not everything the audit asked for there is
done - the button is still a disabled control rather than a
keyboard-reachable always-focusable one, and there are still no visible
focus rings anywhere in the app - so that accessibility-affordances audit
finding stays open in `docs/IDEAS.md` for that remainder.

`Queue._load()` in `src/reclaim.py` already caught
`(json.JSONDecodeError, OSError)` around its `json.load()` call by the time
this pass started; confirmed rather than re-fixed.

What is still not done, and stays in `docs/IDEAS.md` as the live remainder
of the plan: everything outside this repo (generating the real password
hashes, standing up `tailscale serve`, testing from a device that has
actually left the property, adding the one port to the friend's existing
device-tag grant) plus login-page visual polish and password-manager
`autocomplete` attributes, which the plan always scoped as a later
cosmetic pass.

`python -m pytest tests -q`: 126 passed.

---

## 2026-09-14 - Trimming completed narrative out of IDEAS.md

`IDEAS.md`'s own audit named this against itself: the file's header says
settled decisions and completed features belong here, but Current Focus
opened with three paragraphs recapping a build pass and a competitive
landscape re-scan that were both already done, and the protected-media
exclusion gap was stated three times over (Current Focus, an "overridden
recommendation" retrospective entry, and the "Protected-media exclusion
list" entry itself). Current Focus now states only the one live gap; the
retrospective entry is gone, since it added nothing "Protected-media
exclusion list" didn't already say as pending work. The build pass and the
landscape re-scan are recorded in this file's other 2026-09-14 entries, not
restated in the backlog.

---

## 2026-09-14 - Closing the pre-ship audit's HIGH and MEDIUM findings

The architecture and UI review recorded under "Audit findings" in
`docs/IDEAS.md` turned up two HIGH and several MEDIUM findings against the
combined build pass. The two HIGH findings and four of the MEDIUM findings
are fixed; the remaining MEDIUM and LOW findings (watcher-mismatch warning
coverage, blocking GUI actions, GUI visual polish, the destructive-confirm
affordances, and the README dependency claim) are left in `docs/IDEAS.md`.

**`reclaim._fetch_single()` swallowed a "record is gone" 404 into an
uncaught `OSError` instead of returning `None`.** Both `SERVICE_ERRORS`
wrapping in `lib.sonarr()`/`movie_lib.radarr()` discarded the underlying
HTTP status, so a series or movie deleted out from under a run raised
rather than resolving cleanly. That broke the canary re-verification path
in `execute()` on every successful run: the delete really happened, but the
raise happened before `queue.mark_removed()` ever ran, so the queue kept
recording it as `PENDING` and the History tab stayed empty after a genuine
removal. `_fetch_single()` now builds its URL and calls `client.fetch()`
directly, catching `HTTPError` itself: a 404 returns `None` as documented,
any other service failure raises `ReclaimError` (visible to the GUI, unlike
a bare `OSError`).

**Two `Queue` instances - one per open browser tab - could clobber each
other's state.** `Queue._save()` rewrote the whole on-disk document from
memory with no reload, and NiceGUI hands out a fresh `Queue` per connected
tab over the same file. A stale tab's Cancel or flag could silently
overwrite a concurrent change from another tab, including a tab executing
an item another tab had already cancelled. `_save()` now reloads the
on-disk document and merges in only the items this instance itself
dirtied, tracked via a `_dirty_ids` set; `gui/main.py`'s `do_execute()` now
re-reads a fresh queue immediately before executing and filters to items
still `PENDING` and due.

**Nothing cross-checked identity before deleting, only the service id.** A
reused Sonarr/Radarr id (a database restore, a remove-and-re-add) could
carry a week-old flag to a different show or movie under a name a human
never confirmed. A new `_identity_mismatch()` check compares `tvdb_id` (TV)
or `(title, year)` (movies) between the evidence captured at flag time and
the live record, in both the bulk re-verify pass (interlock 3) and the
per-item pre-delete re-read (interlock 6); a mismatch aborts the whole run
with a `ReclaimError` rather than being folded into the ordinary
return-to-PENDING path.

**Duplicate flagging had no safe outcome.** `Queue.flag()` now dedupes
against an existing `PENDING` record for the same `(kind, service_id)`,
returning the existing item's id rather than creating a second one; once
that record is cancelled or removed, the same id is flaggable again. The
GUI's review table re-reads the queue on every render and shows a disabled
"Already flagged" button instead of a clickable one for anything already
`PENDING`.

**The stdlib-boundary test could not fail on this repo's Python.**
`test_broomarr_and_reclaim_import_with_nicegui_blocked` built its
meta-path finder on the deprecated, and as of Python 3.12 no-longer-
consulted, `find_module()` hook, which silently never fires - confirmed
directly, since the old-style finder let `import nicegui` through with no
error at all. The finder now defines `find_spec()`, and a new self-check
test proves the block is real by attempting `import nicegui` (installed in
the dev environment) through the same finder and requiring it to fail.

**`movie_facts()`/`MovieFacts` were dead code**, tested but never called;
`MovieLibrary.verdict()` read `hasFile`/`status` straight off whatever
movie dict the caller passed in, which could be a stale in-memory copy.
`verdict()` now looks the movie up by id through `movie_facts()`, which
gained a `status` field so `verdict()` keeps its status-specific messages;
a missing id is now its own explicit "unknown blocks" reason.

**`src/` still told the user Broomarr never deletes anything**, in the
module docstring, `USAGE`, `scan()`, `movie_scan()` and
`dry_run_report.render()` - missed by the CLAUDE.md/README/DevContext
rewrite earlier the same day, since that pass did not touch `src/`. Each
now states the narrow claim precisely (this scan, this report, does not
delete anything by itself) and points at the GUI's Hold Queue as where a
confirmed removal actually happens.

`python -m pytest tests -q`: 85 passed.

---

## 2026-09-14 - The GUI, and telling the safety story straight

Fourth and fifth steps of the build brief in `docs/design/build-brief.md`,
following the reclaim path. Added `gui/`, a NiceGUI interface, and rewrote
`CLAUDE.md`, `README.md` and `docs/References/DevContext.md` to describe
what the tool can now do rather than keep repeating "Broomarr never
deletes," which stopped being true the moment `src/reclaim.py` existed.

The dependency boundary from `docs/design/gui-design.md` is drawn at the
directory level, and `tests/test_no_gui_dependency.py` checks it directly
rather than trusting a comment: `src/broomarr.py` and `src/reclaim.py` stay
standard-library-only forever (one test greps both files for the string
"nicegui"; another imports both in a subprocess with a `sys.meta_path`
finder that refuses to import nicegui at all, standing in for "nicegui is
not installed" without a second virtualenv), while `gui/` is the one place
in the repo allowed to depend on anything. `gui/main.py` binds
`host="localhost"`, never `0.0.0.0`, which the fourth test checks by
reading the source file directly.

`gui/data.py` decides nothing new. Every safe/blocked split and every
reason string it shows is `Library.verdict()` or `MovieLibrary.verdict()`,
unchanged; the module only calls those, caches one scan to
`state/last-scan.json` so the GUI never scans on launch, and adds
`_gather_movies()` as the movie-side equivalent of the existing
`dry_run_report.evaluate()`. Flagging an item from a review tab writes only
to the local hold-queue file - never a request to Sonarr or Radarr. The
six tabs are grouped by mutate-versus-observe: Dashboard, TV Shows, Movies
and Blocked can flag; Hold Queue and History are the only tabs whose code
path can reach `reclaim.execute()`, and Hold Queue renders two physically
separate lists (ON HOLD, READY TO REMOVE) rather than one list with a
disabled button, so an item still on hold has no execute control to
misclick.

Along the way, `dry_run_report.evaluate()`'s per-item dict gained an `id`
key: it already carried `tvdb_id`, but `reclaim.execute()` matches Sonarr
records by Sonarr's own internal series id, which is a different number.

One deliberate scope trim against the full visual spec, disclosed rather
than silently dropped: the grid/table view toggle, poster proxying and its
`state/covers/` cache, the amber close-call band keyed to
`MARGIN_DAYS_RISKY`, and tabular-numeral typography are not built. Nothing
that decides, holds, or removes anything is affected - only how it looks.

The documentation rewrite applies section 5 of
`docs/design/reclaim-backend-design.md` close to verbatim, with two
corrections where the drafted text no longer matched the repo: the README
line "Broomarr holds no state... and writes to none of them" was already
false (the reclaim path keeps `state/`), so the Scope section now says so
directly instead of repeating a guarantee the code had dropped; and
`DevContext.md`'s "no automation, no deletion" line in the Maintainerr
comparison became "no automation, and no deletion that a person did not
confirm twice." Everything else - the seven-interlock list, the "what is
genuinely worse than before" paragraph, and the "there are no runs nobody
watched" argument - is applied as drafted, because that paragraph is the
one this whole rewrite exists to keep honest.

Smoke-tested live: `python -m gui.main` starts against the real
`config/config.json` in this environment and serves on
`http://localhost:8472`; `netstat` confirms it listens only on
`127.0.0.1:8472` and `[::1]:8472`, never `0.0.0.0`. The acceptance
criterion's hand-test - flag one small real item, watch it sit in the
hold, confirm the execute control is absent, then cancel it, without
executing a real deletion - is recorded separately once it has actually
been run against the live library.

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

## 2026-09-14 - The reclaim path: a staged hold queue and the delete calls

Third step of the build brief. Added `src/reclaim.py` - the only module in
Broomarr that can write to Sonarr or Radarr. It imports `broomarr` and calls
`Library.verdict()`/`MovieLibrary.verdict()`; `broomarr.py` never imports
`reclaim`, and stays GET-only forever, which `tests/test_reclaim.py`'s
`test_broomarr_module_issues_no_non_get_request` checks directly by scanning
the source for `method=`.

Three stored states - PENDING, CANCELLED, REMOVED - persisted in
`state/reclaim-queue.json` (new `state/` gitignore entry). "DUE" is never
stored: `Queue.is_due()` computes it from `flagged_at` plus the new
`hold_days` config key (default 7) at query time, so nothing is running when
nobody has the GUI open. Both the queue file and the append-only removal
history at `state/reclaim-history.json` are written atomically, via a
sibling `.tmp` file and `os.replace()`.

`reclaim.execute()` runs seven interlocks, in order, before any delete, and
aborts the whole run rather than acting partially if any of them (other than
re-verification, which only drops the items that fail it) refuses:

1. Scan freshness - refuses evidence older than `max_scan_age_days` (new
   config key, default 3).
2. Hold elapsed - refuses anything not yet due.
3. Live re-verification - recomputes `verdict()` from scratch against Sonarr/
   Radarr/Tautulli right now; anything that no longer comes back safe returns
   to PENDING with the new reason and a restarted hold, and is excluded from
   the rest of the run.
4. Cap - refuses the entire run over `max_items` (default 10) or `max_bytes`
   (default 250 GB), abort-not-truncate.
5. Canary - deletes the smallest item alone first and confirms the service
   reports it gone before touching anything else.
6. Per-item re-read immediately before each delete call.
7. Record immediately after each individual deletion, not at the end of the
   run - a crash mid-run leaves a truthful account of what is already gone.

The two delete calls: `DELETE {sonarr_url}/api/v3/series/{id}?deleteFiles=
true&addImportListExclusion=false` and `DELETE {radarr_url}/api/v3/movie/
{id}?deleteFiles=true&addImportExclusion=false` - note the differing
parameter name. The Sonarr route and method were verified live against this
environment's real Sonarr instance: a full OpenAPI/Swagger JSON spec could
not be fetched through the browser-facing Swagger UI (every path returned
either 404 or the HTML shell rather than JSON), so instead a `DELETE` was
sent to a deliberately nonexistent series id (999999999); it came back with
an HTTP 500 whose body showed the request reached Sonarr's real
delete-lookup code path, failing only on "no such id" - confirming the route
and method without touching any real data. Radarr is not configured in this
environment, so its `addImportExclusion` parameter name could not be
verified live and is sourced only from `docs/design/reclaim-backend-design.md`.

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
