# Build brief: movies, reclaim, and the GUI

For the Sonnet build agent. Read `docs/design/reclaim-backend-design.md` and `docs/design/gui-design.md` in full before writing anything, then `src/broomarr.py`, `src/dry_run_report.py`, `tests/test_verdict.py` and `tests/conftest.py` in full. This brief tells you the order and the acceptance criteria; those two design docs tell you the *what* and the *why*, and where they disagree with this brief, they win.

## Ground rules

- **TDD, per the repo's own convention**: "New safety behaviour gets a test first" (`CLAUDE.md`). Every step below names its tests before its implementation. Write the test, watch it fail for the right reason, then implement.
- **No em dashes or en dashes anywhere**, in code, comments, docs or commit messages. Hyphens only.
- **This repo is public.** No real show titles, no real film titles, no profile names, no paths outside the repo, in code, tests, fixtures, docs or commit messages. Test fixtures use placeholder titles exactly as `tests/test_verdict.py` already does ("A Show", "Watcher").
- **Commit in logical chunks**, one per numbered step below. Do not batch steps into one commit.
- Do not push.
- `python -m pytest tests -q` must pass at the end of every step, not just at the end of the build.

---

## Step 1: close the empty-versus-unreadable collapse (TV side)

This is first because everything after it attaches a delete button to `verdict()`'s output. See `reclaim-backend-design.md` section 2 for the full defect analysis.

**Tests first**, in `tests/test_verdict.py`, using the existing `library()` / `checked_library()` helpers:

- `test_empty_episode_list_blocks_rather_than_passes` - Sonarr returns a literal `[]` for `/api/v3/episode`, everything else is a textbook safe show. Assert `safe is False` and that a reason mentions the episode list. This test fails on the current code; confirm that before fixing.
- `test_null_episode_response_blocks` - the fetch returns `None`.
- `test_non_list_episode_response_blocks` - the fetch returns a dict.
- `test_all_episodes_unaired_blocks_on_empty_on_disk` - a real list whose episodes all lie in the future, so `on_disk_eps` is legitimately empty. Assert it blocks, and on the upcoming reason as well as the empty-on-disk one.

**Implementation** in `src/broomarr.py`:

- Add `class UnreadableFacts(Exception)` at module level, near `SERVICE_ERRORS`.
- In `episode_facts()`, before the loop, raise `UnreadableFacts` with a message naming the series id and the failure kind for each of: response is `None`, response is not a `list`, response is an empty `list`. Use an explicit `isinstance` check, not a truthiness test, so the three messages stay distinct.
- Change `episode_facts()`'s third return value to `None` rather than a set on any path that did not establish the on-disk episodes. With the raise above this is belt-and-braces and it makes the contract self-documenting; keep both.
- In `verdict()`'s deep branch, add an explicit `if on_disk_eps is None:` block, and separately `if not on_disk_eps:` appending "no episodes with files found on disk, nothing to verify against." `verdict()`'s existing `except Exception` already catches `UnreadableFacts`; leave that handler as it is.
- Update `explain()` and `dry_run_report.evaluate()` for the new `None` case. `evaluate()`'s `except Exception: pass` at line 91 must also handle `on_disk_eps is None` explicitly rather than silently keeping its initialised empty set.

Update `CLAUDE.md`'s Invariants with one sentence recording that an empty or unreadable episode list blocks, and add a `docs/HISTORY.md` entry. Per `feedback_doc_follows_fix`, the doc update is part of this commit, not a follow-up.

---

## Step 2: Radarr and the movie verdict

See `reclaim-backend-design.md` section 1. Pattern-copy `Library` closely; this is an extension of an existing shape, not a new design.

**Tests first**, in a new `tests/test_movie_verdict.py`, mirroring `test_verdict.py`'s fixture-helper style (`movie()`, `movie_history_row()`, `movie_library()`):

- `test_finished_movie_is_safe`
- `test_movie_with_no_file_blocks`
- `test_unreleased_movie_blocks` - `status` is `announced`.
- `test_in_cinemas_movie_blocks` - `status` is `inCinemas`; a digital release is still coming.
- `test_unrecognised_status_blocks` - `status` is `"somethingNew"`.
- `test_partial_view_blocks` - a history row with `watched_status` 0.3. **This is the most important test on the movie side**; a partial view is the entire signal for a film.
- `test_no_history_blocks`
- `test_a_different_user_watching_it_is_not_enough`
- `test_recent_view_blocks_rather_than_qualifies`
- `test_missing_last_view_timestamp_blocks`
- `test_title_matches_but_year_does_not_is_not_a_match` - the join is two-part.
- `test_uncoercible_year_row_is_not_counted_as_watched`
- `test_duplicate_title_and_year_in_radarr_blocks_both`
- `test_unreachable_radarr_blocks_rather_than_skips`
- `test_movie_facts_returns_none_not_empty_for_a_missing_id`

**Implementation** in `src/broomarr.py`:

- Move `matches_watcher()` to a shared location (module-level function taking the watcher string, or a small mixin) so `Library` and `MovieLibrary` share one copy of the rule. Do not duplicate it. The existing `test_verdict_uses_the_same_matching_rule_as_matches_watcher` must still pass.
- `MovieLibrary` with `radarr(path)`, `movies()`, `movie_watch_index()`, `movie_facts(movie_id)` returning `MovieFacts | None`, and `verdict(movie, users)` with **no `deep` parameter**.
- `load_config()` gains optional `radarr_url` / `radarr_api_key`. Do not add them to the required-key list. One-without-the-other is a `SystemExit` naming the missing key.
- `movie_watch_index()` emits a loud warning, in the same shape as `_warn_if_watcher_unmatched()`, when Tautulli returns zero movie-history rows, so a silently-clean scan cannot be mistaken for a working one.
- CLI: `--movies` scans films, `--all` scans both when Radarr is configured. Update `USAGE`, the module docstring, `scripts/run.bat`'s prompt, and `README.md` together.

---

## Step 3: `src/reclaim.py`, the staged queue and the delete path

See `reclaim-backend-design.md` section 3. Stdlib only. `reclaim` imports `broomarr`; `broomarr` never imports `reclaim`.

**Tests first**, in `tests/test_reclaim.py`, with an injectable `fetch`/`request` and an injectable `now`, exactly as `Library` does, plus `tmp_path` for the queue file. Assert on the recorded call list, never on a live service:

- `test_flagging_writes_no_request` - flagging is local state only.
- `test_item_inside_hold_cannot_be_executed`
- `test_hold_elapsing_does_not_delete_anything_on_its_own` - advance `now` well past the hold, run nothing, assert zero requests. This is the test that encodes the central claim of the whole design.
- `test_execute_refuses_a_stale_scan`
- `test_execute_reverifies_and_drops_an_item_that_became_unsafe` - assert it returns to PENDING with the new reason and that no delete was issued for it.
- `test_cap_exceeded_aborts_the_whole_run_rather_than_truncating` - assert **zero** deletes, not "the first N."
- `test_canary_is_the_smallest_item_and_runs_alone_first`
- `test_a_failed_canary_stops_the_run` - assert exactly one delete attempted.
- `test_delete_url_is_exactly_right` - assert the method is `DELETE` and the URL carries `deleteFiles=true` and the correct exclusion parameter for each service. An API parameter typo on a delete call fails in the wrong direction.
- `test_history_is_written_after_each_item_not_at_the_end` - simulate a failure on item 2 and assert item 1 is recorded.
- `test_cancel_works_from_both_pending_and_due`
- `test_queue_file_write_is_atomic` - assert `os.replace` is used and no partial file is observable.
- `test_broomarr_module_issues_no_non_get_request` - extend whatever coverage exists; `broomarr.py` must remain GET-only.

**Implementation:** `http_request(url, method, headers, payload)` lives in `reclaim.py`, not `broomarr.py`. Queue at `state/reclaim-queue.json`, history at `state/reclaim-history.json`, both atomic writes. Add `state/` to `.gitignore`. New optional config keys `hold_days` (7), `max_scan_age_days` (3), `max_items` (10), `max_bytes`. Implement the seven interlocks in the order given in the design doc, with a comment on each naming what it protects against.

Before writing the delete URLs, verify both parameter names against the live instances' own API documentation rather than trusting the design doc. Note in the commit message which you verified.

---

## Step 4: the GUI

See `gui-design.md` in full. New top-level `gui/` with its own `requirements.txt` (`nicegui>=2.0`). Follow `AudioManager/gui/` for structure: `main.py` with a `NAV_GROUPS` sidebar, one module per tab.

**Test first**: `tests/test_no_gui_dependency.py` asserting that `broomarr` and `reclaim` import successfully with no NiceGUI present and that neither module's source contains `nicegui`. Also assert the GUI binds `localhost`, not `0.0.0.0`.

Then build, in this order, committing each: Dashboard (cached state, no auto-scan, service health panel, watcher-mismatch banner) -> Blocked (read-only, no controls at all) -> TV Shows -> Movies -> Hold Queue -> History. Blocked before the flaggable tabs is deliberate: it is the read-only surface, it exercises the evidence drawer, and getting it right first means the flag control is added to a screen that already renders evidence correctly.

Non-negotiables from the design: the two-group sidebar with REVIEW and RECLAIM visibly separated; red used nowhere except the execute control; no "select all" control anywhere; no path from a blocked item to a flag; posters proxied server-side so the API key never reaches the browser; distinct empty states for "nothing safe", "not scanned yet" and "watcher matches nobody"; typed confirmation on execute; cancel never confirms.

---

## Step 5: documentation

Apply the drafted replacement text from `reclaim-backend-design.md` section 5 to `CLAUDE.md`, `README.md` and `docs/References/DevContext.md` **verbatim unless the code you actually built diverges from the design**, in which case correct the text to match the code and say so in the commit message. If you find yourself softening the "what is genuinely worse than before" paragraph, stop: that paragraph is the point of the rewrite.

Then add a `docs/HISTORY.md` entry in the existing style (prose, dated, leading with what changed and why, naming the specific thing that was wrong before) and move the now-settled `docs/IDEAS.md` entries across per that file's own convention.

Before editing `CLAUDE.md`, check its size budget; it is close to the point where the workspace's BLOAT limits bite. The replacement text is longer than what it replaces, so trim elsewhere in the same edit rather than editing twice.

---

## Acceptance

- `python -m pytest tests -q` green.
- `python src/broomarr.py --check` green against live services, and the same for Radarr.
- A real hand-run of the GUI against the real library: flag one small item, confirm it sits in the hold, confirm the execute control is absent, then cancel it. **Do not execute a real deletion as part of the build.** The first real removal is the user's call, not the builder's.
- `git status` clean of stray files; `state/`, `captures/` and `gui/.cache/` all gitignored.
