# Backend design: movies, the reclaim path, and the empty-versus-unreadable fix

Status: design, not built. Companion to `docs/design/gui-design.md` (the interface) and `docs/design/build-brief.md` (the ordered build steps).

**Why this file is here and not appended to `docs/References/DevContext.md`.** DevContext is the account of the architecture that exists and the arguments that produced it, and one of those arguments is "Why it cannot delete," which this design contradicts. Writing a proposal into that file would leave DevContext simultaneously asserting and denying the same property, which is worse than either. So the proposal lives here while it is a proposal. Section 5 below drafts the replacement text for the affected invariant sections of `CLAUDE.md`, `README.md` and DevContext itself, to be applied by the builder **in the same commit as the code that makes it true**, never before and never after.

---

## 1. Movie support via Radarr

### 1.1 What is genuinely simpler, and what is not

Radarr has no episode concept, so the per-episode set difference has nothing to operate on. One film either has a file or does not, and Tautulli's `media_type=movie` history gives a single watched-or-not fact per user per film. That removes the enumeration machinery and, with it, the two traps DevContext's second and third sections describe: there is no count that can carry a hidden filter, because there is no count.

What does **not** get simpler is the join, and this is where the movie side can quietly reintroduce the failure the TV side was built to prevent. "Never decide from a count" translates on the movie side to: **never decide from how many films somebody watched, and never decide from an aggregate on the Radarr side either.** The decision is per film, keyed on an identifier, or it is not made.

It also does not get simpler on the unknown-blocks axis. Fewer facts to establish means each one carries more weight, and a movie that cannot be matched to any Tautulli history row is indistinguishable from a movie nobody watched unless the code makes it distinguishable. That is the same collapse Deleterr ships with (`docs/ALTERNATIVES.md`), and the movie side is where Broomarr would be most likely to acquire it, because the natural shape of "did they watch this film?" is a boolean and a boolean has no room to say "could not tell."

### 1.2 The join key

Sonarr's `/api/v3/series` carries `tvdbId`; Radarr's `/api/v3/movie` carries `tmdbId` and `imdbId`. Tautulli's `get_history` rows carry neither. They carry `title`, `year`, `rating_key`, `friendly_name`, `watched_status` and `stopped`.

So the join key is **`(normalised_title, year)`**, a two-part identifier, not a title alone. This is strictly better than the TV side's current lowercased-title-only join, whose collision risk `docs/IDEAS.md` already tracks as a structural gap: two films sharing a title are common (remakes are the norm in film, not the exception) but two films sharing a title *and* a release year are not.

Normalisation is `title.strip().lower()` and nothing more. Resist the temptation to strip punctuation, articles or diacritics: every such rule makes the join looser, and a looser join on this side means crediting one film's watch history to a different film, which produces a false safe. A film that fails to match because of a stray colon blocks, which is the correct direction to fail.

`year` is coerced through the existing `_to_int()`. A Tautulli row whose year will not coerce is skipped, exactly as a row with an uncoercible season or episode is skipped today. A Radarr movie with no year cannot be joined and must block with a named reason.

**Ambiguity blocks.** If two Radarr movies normalise to the same `(title, year)` key, both block with "two library entries share this title and year, cannot tell which was watched." This is the warning `docs/IDEAS.md` asks for on the TV side, implemented on the movie side from the start rather than retrofitted. The TV-side equivalent is left as its existing backlog item; do not scope-creep it into this build.

### 1.3 The movie facts, and the `None` discipline

```
MovieFacts:
    on_disk    bool           does Radarr hold a file for this movie
    released   bool           has it been released (see below)
    size_bytes int
```

`movie_facts()` returns a `MovieFacts` **or `None`**, and `None` means "could not establish," never "there is nothing." This is reaper's `Mapping | None` idiom (`docs/ALTERNATIVES.md`, "Adopt from reaper regardless of the fork decision") applied at the point where it was needed.

The critical detail, and the reason this is not just a type annotation: **`movie_facts()` derives its facts from the single movie record Radarr returns, and it must verify that a record was actually returned for the requested id.** `GET /api/v3/movie/{id}` returns the movie object; an id that no longer exists returns 404, which raises through `SERVICE_ERRORS`. But the bulk `GET /api/v3/movie` path used by the scan returns a list, and a movie missing from that list is silently absent rather than an error. So the scan builds its index from the bulk response and any id lookup that misses returns `None`, which blocks.

`released` is derived conservatively. Radarr's `status` field takes `announced`, `inCinemas`, `released` and `deleted`. Only `released` counts as released. `inCinemas` explicitly does not: a film in cinemas has a digital release still to come, which is the movie-side analogue of "more episodes are coming." A `status` value the code does not recognise blocks rather than defaulting either way, on the same unknown-blocks logic, and this must be a literal membership test against a known set rather than a truthiness check or an inequality, per the absent-versus-malformed rule.

### 1.4 The movie verdict

`MovieLibrary.verdict(movie, users)` returns `(safe, reasons)` with the same contract as `Library.verdict()`: every branch that cannot establish a fact appends a reason.

Conditions, all of which must hold:

| # | Condition | Blocks when |
|---|---|---|
| 1 | The movie has a file in Radarr | nothing on disk, so nothing to reclaim and nothing to reason about |
| 2 | Radarr's `status` is a recognised value | an unrecognised status is an unknown |
| 3 | Radarr's `status` is `released` | still announced or in cinemas, a digital release is still coming |
| 4 | Tautulli has history for this `(title, year)` | never started, or the join failed, and those are not distinguishable so both block |
| 5 | The configured watcher appears in that history | somebody else watched it, which is not the same fact |
| 6 | The watcher's view is a real watch, not a partial | `watched_status < 0.5`, same threshold `watch_index()` already uses |
| 7 | A last-view timestamp exists and is outside the quiet period | recent viewing blocks, exactly as on the TV side |
| 8 | The `(title, year)` key is unambiguous in Radarr | two entries share it |

Condition 6 deserves emphasis because it is where the movie side is weakest and the TV side is strong. On the TV side, a partial view of one episode is harmless because the set difference still names the other forty-one episodes. On the movie side, a partial view is the entire signal: somebody who watched thirty minutes of a two-hour film and stopped has not finished it, and if that row is counted as a watch the film reads as safe. Tautulli's `watched_status` is the only thing standing between that person and a deleted film, so **the movie-side watch test must use the same `>= 0.5` threshold and must never fall back to "a history row exists at all."** A film with history rows of which none clears the threshold blocks with "started but never finished," which is a genuinely useful reason string and should be worded as such.

There is no cheap-versus-deep split on the movie side. The bulk `GET /api/v3/movie` already carries `hasFile`, `status`, `year` and `sizeOnDisk` for every film in one call, so there is no per-item request to prefilter away. `MovieLibrary.verdict()` takes no `deep` parameter. Do not add one for symmetry with the TV side; a parameter that is always the same value is a place for a future bug to hide.

### 1.5 Structure

`MovieLibrary` is a sibling class to `Library` in `src/broomarr.py`, sharing `http_get`, `_to_int`, `SERVICE_ERRORS` and `_wrap_service_error` at module level. It gets its own `radarr(path)` method mirroring `sonarr(path)` (API key in an `X-Api-Key` header), its own `movie_watch_index()` mirroring `watch_index()` (one bulk `get_history` call with `media_type=movie`, keyed on `(normalised_title, year)`), and reuses `matches_watcher()`.

`matches_watcher()` should move to a module-level function or a shared mixin rather than being duplicated, so the matching rule still lives in exactly one place. CLAUDE.md's rationale for centralising it holds identically on the movie side: a second copy of the rule will eventually drift and then lie.

Config gains `radarr_url` and `radarr_api_key`. **Both are optional.** `load_config()`'s existing required-key check must not gain them. A config with neither is a valid TV-only install; a config with one but not the other is a misconfiguration and must fail loudly at load, naming which one is missing, rather than half-initialising.

---

## 2. The empty-versus-unreadable collapse

### 2.1 The defect as it stands

`episode_facts()` (`src/broomarr.py`, lines 172-210) loops over `self.sonarr("/api/v3/episode?seriesId=%s" % series_id)` and returns `(missing, upcoming, on_disk_eps)`. If Sonarr returns a literal empty JSON array, the loop body never executes and the function returns `([], [], set())` without raising. `verdict()`'s `except Exception` handler does not fire, because nothing was raised. Then:

- `if missing:` is false, so no block.
- `if upcoming:` is false, so no block.
- `unwatched = sorted(set() - users[watcher]["eps"])` is empty, so `if unwatched:` is false, so no block.

Three consecutive falsy checks no-op, and a series reads as safe on the strength of a response that established nothing. This is a fail-open sitting inside a design whose entire claim is that it fails closed, and it is the one defect class CLAUDE.md names as the only one that matters here.

`http_get` makes it slightly worse: it returns `None` for an empty response body, and `for episode in None` raises `TypeError`, which is not in `SERVICE_ERRORS` but *is* caught by `verdict()`'s broad `except Exception`. So that particular path happens to block, by accident rather than by design, and `explain()`'s separate handler catches it too. The literal `[]` path is the live hole.

### 2.2 The fix

Three changes, each independently sufficient, which is the point. This is the defect class where belt and braces is proportionate.

**(a) A named exception for an unusable response.** Add `class UnreadableFacts(Exception)` at module level. In `episode_facts()`, before the loop:

- If the response is `None`, or is not a `list`, raise `UnreadableFacts` naming the series id and what came back.
- If the response is an empty `list`, raise `UnreadableFacts` with the message "Sonarr returned no episodes for series N, which is not a fact about the series." A real Sonarr series always has at least one episode record; zero is a failure to answer, not an answer.

This must be a membership/type test, not a truthiness test, so that the three cases stay distinguishable in the message even though they all block.

**(b) `on_disk_eps` is `None`, never an empty set, when unestablished.** Change the return contract so the third element is `Optional[set]`. With (a) in place this is belt to (a)'s braces, and it is what makes the contract self-documenting at every call site: a reader of `verdict()` sees `if on_disk_eps is None: block` and knows immediately that emptiness and unreadability are different things here. Both `verdict()` and `dry_run_report.evaluate()` and `explain()` read this field and all three must be updated; `evaluate()`'s `except Exception: pass` at line 91 is currently relying on `verdict()` having already blocked, which stays true but should now also handle the `None` case explicitly rather than leaving `on_disk_eps` as the empty set it initialises to.

**(c) `verdict()` blocks on an empty on-disk set even when the read succeeded.** In the deep branch, after the missing/upcoming checks:

> If `on_disk_eps` is empty, append "no episodes with files found on disk, nothing to verify against."

A series that genuinely has zero episodes on disk is not a deletion candidate anyway: there is nothing to reclaim, and the watcher cannot have watched anything from it. Blocking it costs nothing real and removes the entire class of "empty set silently satisfies a set difference." **This is the change that would have prevented the bug regardless of its cause**, which is why it goes in alongside (a) and (b) rather than instead of them.

### 2.3 Should the TV side be fixed in this pass? Yes.

The brief left this as my call. It is not close.

The argument for deferring is that `docs/IDEAS.md` tracks it as a separate backlog item and this pass is already large. The argument against is decisive: **this pass attaches a delete button to the output of `verdict()`.** The known failure mode of the unfixed bug is "a series reads as safe when the real cause was an unreadable response." Today that costs a wrong line in a printed list that a human then has to act on manually, with the reasoning in front of them. After this pass it costs a title appearing in the safe list, getting flagged by a human who has no way to tell the difference between a genuinely-empty evidence panel and a correctly-empty one, and then being deleted with its files.

Shipping the delete path while leaving a known fail-open in the function that feeds it would be indefensible, and it would also be exactly the failure `docs/ALTERNATIVES.md` names in its own post-mortem: facts gathered correctly, and the conclusion they contradicted left standing next to them.

So: **the TV-side fix lands first in the build order, with its tests, before any movie or GUI code is written.** It is also the cheapest item in the whole build, which makes the ordering free.

The movie-side equivalent is the `None`-not-empty discipline in section 1.3, plus the movie verdict's condition 1: a movie with no file blocks. The movie side has no set difference and therefore no empty-set-satisfies-everything path, but it has the same shape of hole in `movie_watch_index()`: a Tautulli history call that returns zero rows would produce an empty index, every lookup would miss, and every movie would block. That direction is safe but useless and indistinguishable from a working check, which is the same complaint DevContext already makes about the uncoerced-int case. **`movie_watch_index()` must therefore distinguish "Tautulli returned no movie history at all" and surface it as a loud warning in the same shape as `_warn_if_watcher_unmatched()`,** rather than producing a silently clean scan.

---

## 3. The reclaim path

### 3.1 Where it lives, and what stays true

**A new module, `src/reclaim.py`, stdlib only.** `src/broomarr.py` gains no write capability whatsoever: no `--delete` flag, no non-GET request, no filesystem write. Its module docstring's claim about being read-only stays literally true of that file, and the test asserting no non-GET call originates from it stays and is extended.

This is not cosmetic. It means the decision engine and the write engine are separable, separately testable, and separately reviewable, and it means the sentence "the module that decides is not the module that acts" is a property of the code rather than a promise in a document. Maintainerr's third failing, per DevContext, is precisely that rule evaluation and deletion are the same system. This design keeps them apart on purpose, and that separation is the thing that earns the right to add the delete path at all.

`reclaim.py` imports `broomarr` and calls `verdict()`. `broomarr.py` never imports `reclaim`.

### 3.2 The state machine

Four states, persisted in one JSON file at `state/reclaim-queue.json` (gitignored, alongside a `state/` entry added to `.gitignore`):

```
        [ human flags it ]
                |
                v
          PENDING  ------ [ human cancels ] ------> CANCELLED
                |
        [ hold elapses ]
                |
                v
            DUE  --------- [ human cancels ] ------> CANCELLED
                |          [ re-verify fails ] ----> PENDING, hold restarts
        [ human confirms, typed, re-verified ]
                |
                v
          REMOVED (terminal, appended to history)
```

**Nothing moves out of PENDING or DUE without a human.** The hold elapsing is the only automatic transition in the machine, and it moves an item from "cannot be executed" to "can be offered for a second confirmation." There is no scheduler, no cron entry, no background thread and no timer that can reach a delete call. The GUI computes DUE-ness at render time from the stored flag timestamp; nothing is running when nobody has the tab open.

Each queue record holds: kind (`tv` or `movie`), the service id, the title, the size at flag time, the flag timestamp, the full evidence snapshot from `dry_run_report.evaluate()`'s item dict as it stood at flag time, and the state. Writes are atomic (write to a sibling temp file, `os.replace`), because a half-written queue file at the wrong moment is a state nobody has designed for.

`hold_days` is a new optional config key, default 7.

### 3.3 The execute path, interlock by interlock

`reclaim.execute(lib, movie_lib, queue, item_ids, now)` runs the following in order and aborts the whole run on any failure. Each interlock is listed with what it is protecting against, because an interlock whose purpose nobody can state is one somebody will later remove as redundant.

1. **Scan freshness.** Refuse if the cached scan backing the evidence is older than `max_scan_age_days` (new optional config key, default 3). Protects against acting on a verdict computed before the watcher started a rewatch.
2. **Hold elapsed.** Refuse any item whose flag timestamp plus `hold_days` is in the future. Protects against the cooling-off period being bypassed by a direct call.
3. **Re-verify against live services.** For each item, re-fetch and re-run `verdict()` or `MovieLibrary.verdict()` now. Any item that does not come back safe is returned to PENDING with the new reason, its hold restarted, and excluded from the run. Protects against everything that changed during the hold, which is the whole reason the hold exists.
4. **Cap.** Refuse the entire run if it exceeds `max_items` (default 10) or `max_bytes` (default 250 GB). **Abort, never truncate.** Truncating lets sort order pick the victims, which is reaper's point and it is a good one.
5. **Canary.** Execute the smallest item alone. Verify it: re-fetch the series or movie by id and confirm the service reports it gone. Only then proceed to the rest. Protects against a systematically broken delete call costing fifty items instead of one.
6. **Per-item re-read before each call.** Immediately before each delete, re-fetch that item's record and confirm it still exists and still has a file. Protects against acting on a record that changed since step 3.
7. **Record before acting is impossible, so record immediately after.** Append to history and rewrite the queue file after each individual deletion, not once at the end of the run. A crash mid-run must leave a truthful record of what was already removed.

A failure at any point stops the run, leaves every remaining item flagged and untouched, and surfaces the error. There is no partial-success-continue mode.

### 3.4 The actual API calls

`src/broomarr.py`'s `http_get` handles only GET. `reclaim.py` needs a writer, and it should be its own function in `reclaim.py` rather than a generalisation of `http_get`, so that no code path reachable from `broomarr.py` can issue a non-GET request even by accident:

```
http_request(url, method, headers=None, payload=None)
```

built on `urllib.request.Request(url, data=..., headers=..., method=method)`. A 200 or 202 with an empty body is success for both services.

**Sonarr, delete a series and its files:**

```
DELETE {sonarr_url}/api/v3/series/{id}?deleteFiles=true&addImportListExclusion=false
X-Api-Key: <key>
```

`deleteFiles=true` removes the files from disk as well as the database row. `addImportListExclusion=false` is deliberate and must be passed explicitly rather than left to the default: excluding the series from import lists is a separate, stickier decision that would quietly prevent it ever being re-added, and this tool has no mandate to make it. Re-downloadability is a load-bearing part of the risk argument in `docs/IDEAS.md`, and silently adding an exclusion would undermine it.

**Radarr, delete a movie and its files:**

```
DELETE {radarr_url}/api/v3/movie/{id}?deleteFiles=true&addImportExclusion=false
X-Api-Key: <key>
```

Note the parameter name differs from Sonarr's (`addImportExclusion`, not `addImportListExclusion`). Verify both against the running instances' own `/api/v3/system/status` and their Swagger docs at build time rather than trusting this document; an API parameter typo on a delete call fails silently in exactly the wrong direction, because an unrecognised query parameter is ignored and the delete proceeds with the default.

**The soft-delete option, considered and not chosen for this build.** `docs/IDEAS.md`'s auto-delete sketch proposes unmonitoring plus moving files to a holding location. Unmonitoring is available on both services in bulk (`PUT /api/v3/series/editor` with `{"seriesIds": [...], "monitored": false}`, `PUT /api/v3/movie/editor` with `{"movieIds": [...], "monitored": false}`) and does not touch files. It is not in this build because the hold queue already provides the reversal window it was meant to provide, and because moving files to a holding location means Broomarr gaining filesystem access and path-mapping awareness, which is a far larger change than the delete call itself and is where reaper's canary exists to catch broken path mappings. **The hold is the reversal window; a second one made of moved files is not worth its complexity here.** If that turns out to be wrong, the editor endpoints above are where it would be added, and the state machine already has the state to hang it on.

### 3.5 Rate and blast radius

Deletes are issued serially with a short pause between them, never concurrently. There is no throughput problem to solve (the largest plausible run is ten items) and serial execution is what makes the canary and the per-item re-read meaningful.

---

## 4. Answering DevContext's "Why it cannot delete"

DevContext's argument, in full, is this:

> A tool with the power to delete has to be right every time it runs, including runs nobody watched, runs after a service outage, and runs after a config change somebody made six weeks ago. A tool that only prints a list has to be right only in the moment somebody reads the list and acts on it, with the full reasoning in front of them. The second bar is achievable; the first is not, for a decision this asymmetric.

The argument is correct and this design does not dispute it. **It disputes that the design proposed here is on the first side of that line.**

The argument's premise is the phrase "every time it runs, including runs nobody watched." It is an argument about *unattended* execution: a tool that acts on its own schedule accumulates runs nobody read, and its correctness bar is therefore the union of every state the system could be in across all of them. That is the bar this design does not have to clear, because **there is no run nobody watched.** Concretely:

- **Nothing in this system executes without a person present.** There is no scheduler, no daemon, no cron entry, no background thread, and no timer that can reach a delete call. The only automatic transition in the state machine moves an item from "cannot be executed" to "may be offered," and the offer is made to a human who is looking at the screen. If nobody opens the application, nothing happens, forever. The property DevContext identifies as making an unrun script safe ("an unrun script deletes nothing") is preserved exactly.
- **The decision to delete is never made by the algorithm.** `verdict()` produces candidates, as it always has. A human selects from them, twice, days apart, with the evidence rendered in front of them both times. The algorithm's output is a proposal; the human's confirmation is the decision. The interface is built so that rejecting a proposal is cheaper than accepting one at every step.
- **The service-outage case is handled by the same rule that already handles it.** An unreachable Sonarr blocks, today, in `verdict()`. After this change an unreachable Sonarr additionally aborts the execute path at interlock 3. A failure to establish a fact cannot become a deletion in this design any more than it can become a "safe" in the current one, and the empty-versus-unreadable fix in section 2 closes the one place where it could have.
- **The six-week-old config case is handled by freshness and re-verification.** Interlock 1 refuses to act on a scan older than a few days, and interlock 3 recomputes the verdict from live data at the moment of execution. A stale configuration cannot carry a stale decision through to a file.
- **The asymmetry argument is answered by the hold, not waved away.** DevContext is right that "deleted and should not have been" and "kept and should not have been" are not symmetric outcomes. The response is a reversal window measured in days during which cancelling costs one click, plus a cap that aborts rather than truncates, plus a canary that makes a systematic fault cost one item. The asymmetry is real; the design's answer is to buy back time and bound the blast radius, which is what you do with an asymmetric risk you have decided to take on for a reason.

**What has actually changed, stated honestly:** Broomarr previously could not delete, and now it can, under a specific and narrow set of conditions. That is a real reduction in the safety guarantee and it should be recorded as one rather than argued into nothing. The old guarantee was absolute and cost nothing to state. The new one is conditional and depends on interlocks continuing to work. What justifies the trade is that the manual step was the main friction in actually using the tool, an unused safety tool protects nothing, and the person confirming knows what they watched better than any heuristic does. That is a judgment, not a proof, and the honest version of this documentation says so.

**What has not changed, and must not:** unknown still blocks, no decision is made from a count, `verdict()` is still incapable of expressing "delete" as an outcome (it returns candidates and reasons, and nothing downstream of it acts without a human), and `src/broomarr.py` still contains no write call.

---

## 5. Proposed replacement text

Apply these **in the same commit as the code that makes them true.** A document that claims a safety property the code does not have is worse than no document; a document that denies a property the code does have teaches the reader to stop believing it.

### 5.1 Proposed `CLAUDE.md` replacement text

Replace the current first Invariants paragraph:

> **Broomarr never deletes.** No `--delete` flag, no write call to any API, no filesystem access. If a request would add one, say no and explain why - `docs/References/DevContext.md` has the argument. This is the property the whole safety case rests on.

with:

> **Nothing deletes without a human confirming it twice, days apart.** Deletion lives in `src/reclaim.py` and nowhere else. `src/broomarr.py` is still read-only: no `--delete` flag, no non-GET request, no filesystem access, and it never imports `reclaim`. The decision engine and the write engine are separate modules on purpose, because Maintainerr's third failing was that rule evaluation and deletion were one system.
>
> **No schedule, no daemon, no timer ever reaches a delete call.** A flagged item sits in a hold queue for `hold_days`; the hold elapsing only makes it *offerable*, and a person must then confirm again, by typing, against a freshly recomputed verdict. If nobody opens the GUI, nothing is ever deleted. "An unrun script deletes nothing" still holds, and it is still why this is safe to rely on.
>
> **Seven interlocks guard the execute path** (`src/reclaim.py`): scan freshness, hold elapsed, live re-verification, caps that abort rather than truncate, a canary delete of the smallest item first, a per-item re-read before each call, and a record written after each individual deletion rather than at the end of the run. Removing or weakening any of them is the change to refuse. `docs/design/reclaim-backend-design.md` section 4 states what each one protects against; an interlock whose purpose nobody can state is one somebody will delete as redundant.
>
> **`verdict()` still cannot express "delete."** It returns candidates and reasons, exactly as before, and nothing downstream of it acts without a human. Every rule below about unknowns and counts applies unchanged, and matters more now than it did when the output was only ever printed.

Also replace, in the Layout section:

> `src/broomarr.py` is the whole tool - standard library only, no dependencies, Python 3.8+.

with:

> `src/broomarr.py` is the decision engine and `src/reclaim.py` is the write path: both standard library only, no dependencies, Python 3.8+, both unit-testable with an injectable `fetch` and `now` and no network. The CLI must keep working on a bare Python install with no `pip install` step, forever. `gui/` is the interactive interface and is the only part of the repo permitted a dependency (NiceGUI); it contains no safety logic, and `tests/test_no_gui_dependency.py` asserts that neither core module imports it.

### 5.2 Proposed `README.md` replacement text

Replace the section currently headed "Broomarr never deletes anything":

> ## Broomarr never deletes anything
>
> No `--delete` flag, no write call to any API, no filesystem access. This is not a feature waiting to be added - it is the property everything else rests on. A tool that can delete has to be right on every run, including the ones nobody watched. A tool that prints a list has to be right only while somebody is reading it, with the reasoning in front of them.

with:

> ## Broomarr never deletes on its own
>
> There is no schedule, no daemon and no timer that can delete anything. Nothing is ever removed by a run nobody watched, because there are no runs nobody watched: if you do not open Broomarr, nothing happens.
>
> What it can do, since you asked for it in the interface, is carry out a removal **you confirm twice, days apart**. You flag a candidate; it sits in a hold queue for a week; when the hold elapses Broomarr recomputes the whole verdict against live data, tells you if anything changed while it waited, and only then offers you a confirmation you have to type. Cancelling is one click at any point, and it never asks you to confirm the cancel.
>
> Around that sit seven interlocks: it refuses to act on a stale scan, it re-verifies every item against live Sonarr, Radarr and Tautulli at the moment of execution, it aborts rather than truncates when a run exceeds its caps, it deletes the smallest item first and checks that it worked before touching anything else, it re-reads each item immediately before removing it, and it writes the record after each removal rather than at the end. A tool that deletes needs to be right on every run; this one only ever runs while you are watching it, and it spends that run trying to talk you out of it.
>
> The decision engine cannot delete. `src/broomarr.py` makes no write call to anything and holds no `--delete` flag; the removal path is a separate module you have to deliberately reach. The part that decides is not the part that acts, and that is enforced by the code rather than promised by this paragraph.

Also replace the Scope section's status line:

> **Status:** Active development. TV support is complete; movie support is next.

with:

> **Status:** Active development. TV and movie support, a local web interface, and a confirm-then-hold removal flow.

And the Scope paragraph's first sentence:

> TV only. Movies are a simpler version of the same join and are planned next.

with:

> TV and movies. The movie join is a simpler version of the same idea: Radarr has no episodes, so one film either has a file or does not, and the join is on title and year rather than a per-episode set. Radarr is optional - a config without it is a valid TV-only install.

### 5.3 Proposed `docs/References/DevContext.md` replacement text

Replace the closing section:

> ## Why it cannot delete
>
> Broomarr makes no write calls and touches no files. It is not a limitation to be lifted later - it is the property that makes the rest tolerable.
>
> A tool with the power to delete has to be right every time it runs, including runs nobody watched, runs after a service outage, and runs after a config change somebody made six weeks ago. A tool that only prints a list has to be right only in the moment somebody reads the list and acts on it, with the full reasoning in front of them. The second bar is achievable; the first is not, for a decision this asymmetric.
>
> Deletion stays a deliberate manual action in Sonarr. That is the design, not a milestone.

with:

> ## Why it could not delete, and what changed
>
> This section previously argued that Broomarr must never delete. The argument was this: a tool with the power to delete has to be right every time it runs, including runs nobody watched, runs after a service outage, and runs after a config change somebody made six weeks ago, whereas a tool that only prints a list has to be right only in the moment somebody reads the list and acts on it, with the full reasoning in front of them. The second bar is achievable; the first is not, for a decision this asymmetric.
>
> That argument is still correct, and it is worth reading it as an argument about **unattended execution** rather than about deletion as such. Its load-bearing phrase is "every time it runs, including runs nobody watched." A tool that acts on its own schedule accumulates runs nobody read, so its correctness bar becomes the union of every state the system could be in across all of them. That bar is the one that cannot be cleared.
>
> Broomarr now has a removal path, and it is built to stay on the achievable side of that line rather than to argue the line away.
>
> **There are no runs nobody watched.** No scheduler, no daemon, no cron entry, no background thread, no timer can reach a delete call. The only automatic transition in the reclaim state machine moves an item from "cannot be executed" to "may be offered," and the offer is made to a person looking at the screen. If nobody opens the application, nothing happens, indefinitely. "An unrun script deletes nothing" is preserved exactly.
>
> **The algorithm never decides.** `verdict()` produces candidates and reasons, unchanged. A person selects from them twice, days apart, with the evidence rendered both times, and the interface is built so that rejecting a candidate is cheaper than accepting one at every step. The proposal is the algorithm's; the decision is the person's.
>
> **The outage and stale-config cases are answered by the same rule that already answered them.** An unreachable service blocks in `verdict()` and additionally aborts the execute path. A scan older than a few days cannot be executed against at all, and every item is re-verified against live data at the moment of removal, so a stale configuration cannot carry a stale decision through to a file.
>
> **The asymmetry is answered, not denied.** "Deleted and should not have been" and "kept and should not have been" remain unequal outcomes. The response is a reversal window of days during which cancelling costs one click, caps that abort rather than truncate, and a canary delete that makes a systematic fault cost one item rather than fifty.
>
> **What is genuinely worse than before, stated plainly.** The old guarantee was absolute and cost nothing to state. The new one is conditional and depends on seven interlocks continuing to work, which means it depends on nobody removing one as redundant. `CLAUDE.md` names them and `docs/design/reclaim-backend-design.md` states what each protects against, for that reason. What justifies the trade is that the manual step was the main friction in actually using the tool, an unused safety tool protects nothing, and the person confirming knows what they watched better than any heuristic does. That is a judgment rather than a proof, and pretending otherwise would be the more dangerous document.
>
> **What has not changed:** unknown still blocks, no decision is ever made from a count, and `src/broomarr.py` still contains no write call of any kind. The decision engine and the write engine are separate modules, which is the specific thing Maintainerr does not do and the third reason it was retired.
