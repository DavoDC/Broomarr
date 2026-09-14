# Ideas & Future Work

Single source of truth for all pending work in this repo. Settled decisions and completed features -> `docs/HISTORY.md`.

---

## Current Focus

**Broomarr is ready for testing against the real library, in dry-run/flag/hold/cancel mode - not for a real deletion yet.** The test suite is green. The core safety invariants (hold period, cap-abort-not-truncate, canary-first, re-verify-before-delete) are built and tested, and none of the open audit findings below block read-only or hold-queue use: the destructive-confirm and blocking-GUI-action findings are UX problems on a control that still fails safe, and the rest are cosmetic or test-coverage gaps. This is the next step before further development, and it costs nothing to do now - run scans, flag items, watch them sit in the hold queue, cancel them, and record what breaks here.

**The protected-media exclusion list does not exist yet**, so a confirm
screen with no exclusion support can surface a protected title as a normal
candidate, survived only by the human reading the hold queue and the
week-long hold. That is the next thing worth building, before the first
real removal against the live library if practical - see "Protected-media
exclusion list" below.

---

## Pending - Main Work

*(Ordered by priority. Quick wins go FIRST within each tier - small, unblocked items before large/blocked ones. Items that are blocked or depend on other items go below their prerequisite.)*

---

**Run reaper in dry-run mode against the real library, once, before the next planning round.** The source audit (`docs/ALTERNATIVES.md`, `docs/HISTORY.md` 2026-09-14) found that reaper is the first tool in the survey not disqualified on architecture: it reads Sonarr's episode list as its denominator, rejects `episodeCount`/`totalEpisodeCount` for Broomarr's own reasons, and its unknown-handling is enforced by the type system. The case for maintaining Broomarr now rests partly on an assumption nobody has tested - that reaper's shortlist would be worse than Broomarr's. It ships with `dry_run` on by default plus a host-level environment variable that must be set before any mutating call, so a read-only trial costs nothing but setup time. Run it, compare its shortlist against Broomarr's on the same library, and record the result here. If it is as good, the honest conclusion is that Broomarr's remaining value is exactness and legibility, not capability - which is a fine reason to keep it, but a different one from the reason currently written down.

---

**Surface the incomplete-series protection as a named reason in `explain()`.** reaper shows an operator "episodes are missing" as an explicit protection reason rather than leaving it implicit in the outcome. Broomarr has the same fact and the better version of it (enumerated, not counted) but does not always say so in as many words. Cheap, and it is the kind of thing that makes a shortlist trustworthy to read.

---

**FUTURE OPTION, NOT A DECISION: opt-in auto-delete, armed only after a demonstrated reliability bar.** This is recorded as a proposal under consideration, and it remains one: the human-confirmed hold queue that now exists is deliberately *not* this, and nothing in it arms anything. `CLAUDE.md`, `README.md` and `DevContext.md` no longer claim Broomarr never deletes - see `docs/HISTORY.md`'s GUI entry for the rewrite - but what they describe instead is the confirm-twice flow below, not this option. **The confirm flow is the better answer to the same friction and it costs no automation; auto-delete is only worth reconsidering if that turns out not to be enough.** One piece of this entry's own argument is already built: the History tab is the persisted per-run record that would make any future reliability streak evidence rather than recollection.

The case for opening it: the media is re-downloadable, so the cost of a wrong deletion is usually bandwidth and inconvenience rather than loss, and the manual step is the main friction in actually using the tool. The case against a blanket flip: re-downloadability is not uniform (out-of-print, unusual cuts, anything personal), a wrong deletion is typically noticed weeks later by the person who wanted to watch it, and a *systematic* fault removes fifty shows rather than one, which is expensive even at a low per-item cost. See `docs/ALTERNATIVES.md`, "Are these the right axes?", for the full reasoning.

That shape of risk points at a narrow, staged design rather than a `--delete` flag:

- **Soft delete, never hard.** The armed path unmonitors the series in Sonarr and moves its files to a holding location, or flags them for removal on a timer. Actual deletion happens after a hold long enough for someone to notice - a month, not a day. Nothing is armed that cannot be undone by moving files back.
- **Arm per scope, never globally.** A tag, a specific set of titles, or a single library at a time. The protected-media exclusion list below is a hard prerequisite, not a companion feature - there must be no way to arm before exclusions exist.
- **Caps that abort rather than truncate.** A run that exceeds N items or M bytes stops entirely and reports, rather than deleting the first N. Truncating lets sort order pick the victims.
- **Canary first.** Smallest item, alone, verified, before anything else in the run proceeds. A broken path mapping then costs one file. (This and the previous two are reaper's design, borrowed deliberately - see `docs/ALTERNATIVES.md`.)
- **Two independent switches.** An in-config arm flag and a host-level environment variable, so no single bug or bad config can arm the tool.

"Proven reliable enough to arm" should mean something checkable, not a feeling. A defensible bar: **thirty consecutive days of scheduled dry runs whose shortlists were reviewed, with zero entries a human rejected**, plus a persisted record of each run so the streak is evidence rather than recollection. One rejection resets the count. The streak should be per-scope, since a tool that is reliable on one library has demonstrated nothing about another. Note that this bar is itself a feature to build - run logging and shortlist-diffing between runs - and it is worth building regardless of whether auto-delete ever follows, because a shortlist that changes between runs for no reason is a bug nobody would currently see.

Ordering: this comes after the protected-media exclusion list lands, and after the hold queue has been used in anger for a while. The confirm flow is the better answer to the same friction and it costs no invariant; auto-delete is only worth considering if that turns out not to be enough.

---

**The Sonarr-Tautulli join is by lowercased title, not a stable ID, and two
shows sharing a title would merge their watch history.** `watch_index()` keys
its dict by `grandparent_title.strip().lower()`, and `scan()`/`verdict()`
look up `series["title"].lower()` against it - there is no `tvdbId` or
rating-key cross-check anywhere in the join. Two Sonarr entries with the
same title (a US/UK remake, a reboot with an unchanged name) would read
from the *same* merged bucket of watched episodes, so watching S01E01 of one
could count as watching S01E01 of the other. Not live today - a scan of the
current 197-series library found no duplicate titles - but it is a
structural gap, not a today's-data coincidence, and it gets more likely as
the library grows. Worth deciding whether to key on `tvdbId` (Sonarr has
it; Tautulli's episode history rows do not carry it directly, so it would
need a Sonarr title->tvdbId lookup merged in) or at minimum warn on a
duplicate title the way `_warn_if_watcher_unmatched` warns on a
watcher mismatch.

---

**Remote access, when the GUI needs to become reachable from outside the house: prefer a private mesh network over a port forward.** A mesh VPN such as Tailscale, or its self-hosted equivalent Headscale, binds the app to a private address shared only between enrolled devices. There is no open port for a scanner to find, and someone who is not already on the network cannot reach the login page at all, let alone probe it. The free tier covers a household-sized set of devices, and node sharing invites one specific person to one specific service without handing them the rest of the network. It also replaces the certificate problem: a mesh network encrypts the link without anyone generating a self-signed certificate that every client then has to be told to trust.

The reason to prefer this over a port forward is sharper for a tool like this one than for the popular self-hosted applications it sits alongside. **A hand-written app is a worse thing to expose than a widely used community one.** A popular open-source project has many users, a security contact, published advisories and outsiders who report bugs in it, so when it turns out to be vulnerable a fix usually exists and the task is to have applied it. A tool written by one person for one library has none of that: no one else is reviewing its session handling or its input parsing, no advisory will ever be published for it, and the first person to find a flaw in it will be the one exploiting it. "Keep it patched" is not a strategy for software with no upstream. Given that this particular app is the only entry point that will ever hold a delete path, the asymmetry is worth taking seriously: the worst case is not a leaked watch history, it is someone else driving the deletion.

The same argument generalises beyond this repo. Anything self-written and reachable from outside the house belongs behind the mesh network, and putting one service there is most of the work of putting all of them there, so it is worth doing once and reusing rather than deciding per app.

---

## Audit findings - architecture and UI review, 2026-09-14

*(A pre-ship review of the whole repo as it stands after the combined build pass, not just the new code. Every entry carries an explicit priority: HIGH is safety-relevant or architecturally load-bearing, MEDIUM is a real bug or meaningfully bad UX, LOW is polish and hygiene. Ordered HIGH first.)*

---

**[MEDIUM] The watcher-mismatch warning never reached either the GUI or the movie side.** `_warn_if_watcher_unmatched()` is called from exactly one place, `broomarr.scan()`. `movie_scan()` does not call it, `MovieLibrary` has no equivalent, and the GUI surfaces watcher matching only inside the on-demand "Run health check" panel that a user has to think to press. Two designs asked for more than that and neither was built: `docs/design/gui-design.md` line 117 specifies a full-width banner across every REVIEW tab when the watcher matches nobody, with the explicit reasoning that a GUI presenting "0 safe to remove" as a tidy empty state camouflages the failure better than a terminal does; `docs/design/reclaim-backend-design.md` line 120 specifies that `movie_watch_index()` must distinguish "Tautulli returned no movie history at all" and warn in the same shape. Both failures are fail-closed (everything blocks rather than passing), so this is not a wrong-delete risk, but it is a designed safety surface that was dropped without appearing in the disclosed scope-trim list in `docs/HISTORY.md`, which only names cosmetic omissions. The honest fix is a banner component in the GUI plus the movie-side warning, or a decision recorded here that both were dropped deliberately.

---

**[MEDIUM] Every long-running action blocks the GUI's event loop, with no loading state and nothing preventing a second click.** `do_rescan()` in `gui/main.py` calls `STORE.run_scan()` synchronously inside a NiceGUI click handler, and that is a full library scan: the bulk Sonarr list, the whole Tautulli history, then one `/api/v3/episode` call per surviving candidate. On a library of a couple of hundred series that is minutes during which the server answers nothing at all, for every connected client, while the Re-scan button stays enabled and un-spinnered so the natural response is to click it again. `check_health()` and `do_execute()` have the same shape, and for `do_execute()` a queued second click means a second `reclaim.execute()` run against items the first run already deleted, which lands straight on the 404 path in the first finding above. Wants `run.io_bound` (or an equivalent thread offload), a disabled button plus a spinner for the duration, and a guard against re-entry on the execute path specifically.

---

**[MEDIUM] The GUI reads as a NiceGUI scaffold with dark mode on, not as the Sonarr/Radarr/Overseerr-shaped interface the design asked for.** Setting aside the poster grid and the view toggle, which `docs/HISTORY.md` disclosed as a deliberate trim, several things that cost almost nothing are missing and their absence is what makes the page read as unfinished. The left nav has no active state at all, so there is no way to tell which of the six tabs you are looking at; there are no icons, no hover treatment, and no header bar above the content pane. Styling is ad-hoc inline hex strings assembled by `_card_style()` and `_badge()` rather than a small set of CSS variables, so the palette is restated at a dozen call sites and cannot be adjusted coherently. The REVIEW/RECLAIM split exists in the markup as one `border-top` on a group label, which is not enough to read as the deliberate mutate-versus-observe boundary the design makes it. The Hold Queue's "two physically separate lists" are two identically styled `ui.label` headers over identically styled rows, so the strongest safety affordance in the application looks like one list with two captions. `ui.dark_mode().enable()` in `index()` duplicates `dark=True` in `run()`. Contrast is mostly acceptable but the `#777` group labels on the `#161616` sidebar at 11px fall under 4.5:1. Polish rather than safety, but this is the surface a destructive action lives on and it currently does not look like one that was designed.

---

**[MEDIUM] The destructive confirmation has no accessible affordances.** The typed confirm in `_build_hold()` is a bare `ui.input(placeholder="Type REMOVE to enable")` with no label, so the only instruction disappears the moment a character is typed; the match is exact against `"REMOVE"`, so a trailing space or a lowercase attempt silently does nothing and the user gets no explanation; and the Remove button toggles from disabled to enabled with no announcement, while a disabled button is not focusable and not reachable by keyboard tabbing at all. There are no visible focus rings anywhere in the app. For the one control in the repo that deletes files, "you cannot tell why the button is not working" is the wrong failure mode even though it fails in the safe direction.

---

**[MEDIUM] README tells the reader there are no dependencies and then tells them to run the GUI.** The Setup section says "Python 3.8 or newer. No dependencies, standard library only," and the Running it section says to run `python -m gui.main` or `scripts\run-gui.bat`. `gui/requirements.txt` (`nicegui>=2.0`) is never mentioned in the README, and `scripts/run-gui.bat` checks only for `config/config.json` before invoking `python -m gui.main`, so a reader following the documentation exactly gets a `ModuleNotFoundError` with nothing pointing at the cause. The claim wants qualifying ("the CLI has no dependencies; the optional GUI needs `pip install -r gui/requirements.txt`"), and the launcher wants a friendlier failure when the import is missing. The README also never documents `hold_days`, `max_scan_age_days`, `max_items` or `max_bytes`, which exist only in `config/config.example.json`, even though they are the tunables that govern the delete path.

---

**[LOW] Test gaps worth closing, all of them cheap.** `CLAUDE.md` states that `broomarr.py` "never imports `reclaim`" as a named invariant and no test asserts it (`test_broomarr_module_issues_no_non_get_request` greps for `method=`, which is a different claim). There is no test that a `CANCELLED` item cannot be executed - the current behaviour is safe, since `is_due()` returns `False` for any non-`PENDING` state, but it surfaces as a `ReclaimError` reading "hold period has not elapsed", which is a misleading message for a cancelled item and nothing pins the behaviour down. Nothing under `gui/` is tested at all, including `data.flag()`, which is the function that assembles the evidence dict every interlock later reads. And `Queue._load()` calls `json.load()` unguarded, so a truncated or hand-edited `state/reclaim-queue.json` takes down every tab of the GUI at page build with a raw traceback; there is no test and no recovery path.

---

**[LOW] Dead and leftover code in `gui/`.** `_build_hold()` contains `"hold ends in %d day(s)" % int(remaining) + 1 if False else "hold ends in ~%d day(s)" % (remaining)`, an abandoned ternary with a permanently false condition that shipped as-is. `_build_dashboard()` computes `earliest = min(r["flagged_at"] for r in pending)` and never uses it. `_build_review_table()`'s `show_all_state` parameter is passed a fresh `[False]` literal by both callers, so the state it exists to preserve is discarded on every rebuild. `gui/config.py` defines `COVERS_CACHE_DIR` for a poster cache that was never built. `data.Data.flag()` has an `if kind == "tv": ... else: ...` whose two branches assign `service_id` identically. `reclaim_defaults_hold_days()` is a public-looking helper among underscore-prefixed siblings, defined below its own call site, doing a function-local import.

---

**[LOW] TV sizes round-trip through gigabytes before being stored as bytes.** `data.Data.flag()` stores `int(item["size_gb"] * 1e9)` for TV because `dry_run_report.evaluate()`'s item dict carries only `size_gb`, while the movie path stores the exact `item["size_bytes"]` that `_gather_movies()` kept. Those stored bytes are what interlock 4 sums against `max_bytes`, so the cap is being checked against a lossy number on one of the two sides. Adding `size_bytes` to `evaluate()`'s dict alongside `size_gb` makes the two paths identical and removes the asymmetry.

---

**[LOW] `gui/data.py` only imports successfully because `gui/main.py` happens to import `gui.config` first.** `gui/config.py` is what inserts `src/` onto `sys.path`, and `gui/data.py` does `import broomarr` at line 14, four lines before `from gui import config` at line 18. `gui/__init__.py` is empty, so `import gui.data` on its own (a test, a REPL, any future entry point) raises `ModuleNotFoundError`. Moving the path insertion into `gui/__init__.py`, or importing `gui.config` first in `data.py`, removes an ordering dependency that currently holds by luck. Relatedly, `gui/main.py`'s own docstring says to run `python gui/main.py`, which does not work - that puts `gui/` on the path rather than the repo root, so `from gui import config, data` fails. `CLAUDE.md` and the README both have the correct `python -m gui.main`.

---

**[LOW] Empty states do not distinguish which kind of empty they are.** `docs/design/gui-design.md` line 259 asks for exactly this: "nothing is safe to remove", "the scan has not been run" and "the watcher matches nobody so everything blocked" are three different states that all render as an empty list, and conflating them recreates the failure `_warn_if_watcher_unmatched()` exists to prevent in a prettier form. As built, `_build_review_table()` has two generic strings ("Nothing here yet - run a scan from the Dashboard" and "Nothing is safe to remove right now") and no third state, and neither carries a remedy button.

---

## Lower Priority / Future

*(Ordered by size - smaller/quicker first. These are not urgent but worth doing eventually.)*

---

**Protected-media exclusion list.** Some titles (a specific rewatch favourite, say) and some whole categories (anime as a category, for example) should never be surfaced as a deletion candidate at all, regardless of watch state - not "warn and let a human override," but excluded from `verdict()` before a candidate is ever produced. This wants two levels: an exact-title (or stable-ID) exclude list in `config.json`, and a category/genre-level exclude flag, since Sonarr exposes genre/tag metadata per series. Needs a decision on whether the category match is a hardcoded genre string or a configurable list, and whether exclusion is silent (title never appears anywhere) or shows up in `explain()` as "excluded, not evaluated" for transparency.

---

**GUI visual polish deferred from the build pass.** `gui/main.py` implements every safety-critical behaviour from `docs/design/gui-design.md` verbatim (the hold queue's two physically separate sections, the typed "REMOVE" confirmation, no execute control at all on a held item, Blocked staying read-only) but skips several purely cosmetic details for a later pass: a grid/table view toggle for Movies vs TV Shows, poster proxying with a `state/covers/` cache, the amber close-call band keyed to `MARGIN_DAYS_RISKY` (a plain badge stands in for it today), and tabular-numeral typography. None of these affect what can be flagged, held, or removed - see `docs/HISTORY.md`'s GUI entry.

---

**Exploratory: chat-bot confirmation flow as an alternative to browser + mesh VPN access.** The remote-access plan above (mesh VPN such as Tailscale) assumes a device can run a VPN client freely. Some devices only allow one active VPN profile system-wide, which could conflict with another VPN already in use on that device. If that constraint holds, a chat-bot interface (e.g. a messaging-platform bot) that sends a candidate list and accepts a reply as confirmation could substitute for reaching the web UI directly, without opening a port. This is speculative - the actual constraint needs verifying on the specific device before any design work, and it must not reduce the human-confirms-each-deletion invariant to a single blanket "yes." **This repo is public** - do not record who the approving household members are anywhere in it; a generic "approver" role in config is fine, specific people are not.

---

**Multiple watchers per show, not one named watcher.** `config.json` currently
takes a single `watcher` string matched case-insensitively. Households where
more than one person needs to have finished a show before it is safe to
remove would need the verdict to require all configured watchers, not just
one - matters for shared libraries, not solo ones. `Library.matches_watcher()`
is the single place the matching rule lives, so this change has one seam
rather than several.

---

**The substring watcher match is loose.** `matches_watcher()` is a
case-insensitive substring test, so a configured watcher of `sam` matches a
Tautulli friendly name of `samantha`. That is convenient and it is also a way
to silently consult the wrong person's history. Worth tightening to an exact
match with substring as an explicit fallback, or at least warning when the
configured value matches more than one friendly name.

---

## See Also

- `docs/HISTORY.md` - completed features, settled design decisions, parked ideas
