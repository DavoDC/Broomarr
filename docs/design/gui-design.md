# GUI design: the review-and-reclaim interface

Status: design, not built. This document is the visual and structural specification for Broomarr's local web interface. The backend it sits on (the Radarr join, the staged delete path, the empty-vs-unreadable fix) is specified separately in `docs/design/reclaim-backend-design.md`, and the ordered build steps are in `docs/design/build-brief.md`.

**Why this file is here and not in `docs/References/DevContext.md`.** DevContext is a truthful account of the architecture that exists and the arguments that produced it. This is a proposal for something unbuilt, and visual design at that. Filing it into DevContext would both dilute that file's purpose and make it stop being a reliable description of the shipped system. `docs/design/` is the new home for unbuilt-proposal documents; when a design here ships, the durable part of its reasoning is folded into DevContext and the design file is retired to a HISTORY entry rather than left to rot as a second, stale source of truth.

---

## The stack decision, and the dependency invariant it collides with

`CLAUDE.md`'s Layout section says: "standard library only, no dependencies, Python 3.8+." A web interface with a dark theme, sortable tables, a poster grid, dialogs and a confirmation flow is buildable against `http.server` and hand-written HTML, and it would cost several hundred lines of hand-rolled routing, template assembly, form parsing and client-side JavaScript that nobody has tested, in a repo whose entire safety case is that it is small enough to read.

**Recommendation: use NiceGUI, and re-scope the dependency invariant rather than break it.**

The invariant worth keeping is not "this repo has no dependencies." It is **"the module that decides whether something is safe to delete has no dependencies, and can be read end to end by one person in one sitting."** Those are different claims, and only the second one ever carried weight. The first is a proxy for it.

So the boundary is drawn at the directory:

| Layer | Location | Dependencies | Rule |
|---|---|---|---|
| Decision core | `src/broomarr.py` | none, stdlib only | Never imports anything outside the standard library. The CLI must run on a bare Python 3.8 install with no `pip install` step, forever. |
| Reclaim engine | `src/reclaim.py` | none, stdlib only | The write path. Also stdlib only, also unit-testable without a live service or a browser. |
| Interface | `gui/` | `nicegui>=2.0` | May depend on whatever it needs. Contains no safety logic of its own. |

The test that keeps this honest, and which the builder must write: **`tests/test_no_gui_dependency.py` asserts that importing `broomarr` and `reclaim` succeeds with `gui/` absent and NiceGUI uninstalled, and that neither module's source contains an import of `nicegui`.** If the GUI ever becomes load-bearing for a decision, that test fails and tells you so.

**Why NiceGUI specifically, over the alternatives considered:**

- **Precedent on this machine.** `AudioManager/gui/` is a working, non-trivial NiceGUI application built to an explicitly Sonarr/Radarr-shaped design vision, with a solved hot-reload story, a solved theming story, a solved chart story and a solved table-with-pagination story. Per the pattern-copy research approach, adapting a working local example beats building from scratch, and the layout decisions in `AudioManager/docs/References/GUI-Architecture.md` are directly transferable rather than merely inspirational.
- **The event model is safer for a delete button than a hand-rolled HTTP server is.** In NiceGUI a button handler is a Python callable invoked over a per-session websocket, not a URL. There is no `DELETE /api/remove?id=42` route sitting on localhost that any process on the machine, or any page in the browser, can reach by guessing it. A hand-rolled `http.server` would need such a route, and would need CSRF handling and origin checking hand-written to protect it, at exactly the point in the system where a mistake costs files. Fewer hand-written lines on the write path is the whole argument.
- **No JavaScript build step**, so the repo gains one `requirements.txt`, not a `node_modules`, a bundler config and a lockfile.
- Quasar underneath supplies the dark theme, sortable data tables, dialogs, chips and the responsive grid for free, which is most of what this interface is.

**What the choice costs, stated plainly:** the GUI pulls in FastAPI, uvicorn, starlette, Vue and Quasar. That is a very large amount of code sitting next to a tool whose pitch is smallness. The mitigation is the directory boundary above, and the fact that this surface is local-only for now. `docs/IDEAS.md` already argues that a hand-written app is a worse thing to expose to a network than a widely-used community one; that argument gets *stronger*, not weaker, under NiceGUI, because more of the exposed surface is then maintained upstream by people who publish advisories. It is still not a reason to expose it, and this design does not.

**Not chosen, and why:** a stdlib `http.server` plus hand-written frontend loses the argument on the delete-route point above. A desktop toolkit (Tkinter, Qt) cannot plausibly reach the *arr visual language and cannot be viewed from a phone on the same LAN later. Flask or FastAPI directly means hand-writing the frontend anyway, which is the `http.server` option with extra steps.

---

## Design vision

**Sonarr/Radarr/Overseerr:** dark, data-dense, tabs on a left sidebar, content pane on the right. Posters where a human is recognising a title, tables where a human is comparing evidence.

**The interface has one job the CLI cannot do, and it is not prettiness.** `scan()` prints a shortlist; the person reading it then has to go to Sonarr, find each title, and delete it by hand, which is enough friction that the tool gets run and then not acted on. The GUI closes that gap by letting the person who actually knows what they watched confirm or reject each candidate against the evidence, in one place. Every design decision below serves that: **surface the evidence next to the title, make rejecting a candidate as easy as accepting one, and make the delete the least convenient action on the screen.**

**GUI is not a replacement for the CLI** (AudioManager's stated principle, adopted unchanged). `--check`, `--all` and the single-show explain form stay. Anyone scripting Broomarr uses them. The GUI is an alternative interface for the interactive review, not a superset.

**No auto-scan on launch** (AudioManager's rejected auto-run pattern, adopted unchanged, and it matters more here). On launch the GUI reads the cached scan state from `state/last-scan.json` and renders instantly with a visible "last scanned 3 days ago" staleness marker plus a "Re-scan" button. A full scan is hundreds of HTTP calls to two services; firing that on every launch is rude to the services and trains the user to leave a tab open that silently hammers them. More importantly, **a stale scan must be visibly stale**, because acting on a week-old verdict is exactly how you delete something somebody started watching on Tuesday. The staleness marker turns amber past a configurable age and the Hold Queue's execute path refuses to run against a scan older than that threshold at all (see the backend design).

---

## Sidebar: mutate-versus-observe grouping

AudioManager groups its flat tab list into labelled sections that separate write-capable tabs from read-only ones. That principle is more load-bearing here than it is there, because here the write path deletes files rather than committing a mirror repo. The grouping is the primary structural safety affordance of the interface.

```
+------------------------+
|  BROOMARR              |
|  last scan: 3 days ago |
|  [ Re-scan ]           |
|                        |
|  REVIEW                |
|    Dashboard           |
|    TV Shows            |
|    Movies              |
|    Blocked             |
|                        |
|  RECLAIM               |
|    Hold Queue      (2) |
|    History             |
|                        |
|  watcher: <name>       |
|  quiet: 14d  hold: 7d  |
+------------------------+
```

**REVIEW is read-only in the strict sense: nothing in that group can reach a write call to any service.** Browsing, sorting, filtering, expanding evidence, and flagging. Flagging writes only to the local hold-queue file and is fully reversible; it is the one action in REVIEW that persists anything, and it is deliberately not a deletion, which is why it can live there.

**RECLAIM is the only group whose code path can issue an HTTP method other than GET.** Two tabs: the Hold Queue, where flagged items sit out their cooling-off period and are ultimately executed or cancelled, and History, the immutable record of what was removed.

The group labels are rendered, not implied. The RECLAIM header carries a small warning-coloured rule above it so the boundary is visible rather than inferred from tab order.

**Colour discipline:** red appears in exactly one place in the entire interface, the execute control in the Hold Queue. Nothing else is red, not a blocked badge, not a warning, not an error toast. Blocked uses slate, close calls use amber, safe uses the accent green. If a screenshot of this app contains red, something is about to be deleted.

---

## Tab: Dashboard

Landing tab. Answers "what is the state of the library and how stale is what I am looking at" in one screen, with no scrolling.

```
+--------------------------------------------------------------------+
| Dashboard                              scanned 3 days ago  [Re-scan]|
+--------------------------------------------------------------------+
|  +-------------+ +-------------+ +-------------+ +-------------+   |
|  | 197         | | 18          | | 3           | | 53.2 GB     |   |
|  | series      | | candidates  | | safe to     | | reclaimable |   |
|  | in Sonarr   | | (cheap pass)| | remove      | |             |   |
|  +-------------+ +-------------+ +-------------+ +-------------+   |
|  +-------------+ +-------------+ +-------------+ +-------------+   |
|  | 412         | | 31          | | 7           | | 88.0 GB     |   |
|  | movies      | | candidates  | | safe to     | | reclaimable |   |
|  | in Radarr   | |             | | remove      | |             |   |
|  +-------------+ +-------------+ +-------------+ +-------------+   |
|                                                                    |
|  SERVICE HEALTH                                                    |
|    Sonarr    reachable    197 series                               |
|    Radarr    reachable    412 movies                               |
|    Tautulli  reachable    4 friendly names in history              |
|    watcher   matches "<configured name>"                           |
|                                                                    |
|  IN HOLD                                                           |
|    2 items flagged, earliest due in 4 days     -> Hold Queue       |
+--------------------------------------------------------------------+
```

The service-health block is the `--check` output rendered as a panel, run on demand rather than on load, and it fails loudly. **The watcher-mismatch trap that `_warn_if_watcher_unmatched()` exists to catch must be a full-width banner across every REVIEW tab when it fires, not a line in a health panel.** A misconfigured watcher makes a healthy library look completely clean, and in a GUI that presents "0 safe to remove" as a tidy empty state, that failure is even better camouflaged than it is on a terminal.

If Radarr is not configured at all, the movie tiles and the Movies tab are absent, not empty. Movie support is optional: a config without `radarr_url` is a valid TV-only install and must not render a broken half-interface.

---

## Tabs: TV Shows and Movies

Structurally identical, differing only in the evidence columns. Both default to the **safe-to-remove** filter, because that is what the user came for, with a segmented control to widen to all candidates.

Two view modes, toggled, preference remembered in local state:

**Grid** (default for Movies, where recognition is visual and posters are how anyone identifies a film):

```
+----------------------------------------------------------------+
| Movies    [safe 7] [candidates 31] [all 412]     [grid] [table] |
| sort: size v    search: [________]         [ Flag selected (0) ]|
+----------------------------------------------------------------+
|  +--------+  +--------+  +--------+  +--------+  +--------+     |
|  | poster |  | poster |  | poster |  | poster |  | poster |     |
|  |        |  |        |  |        |  |        |  |        |     |
|  |     [x]|  |     [ ]|  |     [ ]|  |     [ ]|  |     [ ]|     |
|  +--------+  +--------+  +--------+  +--------+  +--------+     |
|  Title       Title       Title       Title       Title          |
|  2011 12.1GB 2004 8.4GB  1998 6.0GB  2016 5.2GB  2009 4.4GB     |
|  watched     watched     watched     watched     CLOSE CALL     |
|  184d ago    140d ago     96d ago     61d ago    watched 19d ago|
+----------------------------------------------------------------+
```

Poster tiles carry a checkbox in the corner, the title, year, size, and a one-line verdict summary. A close call (inside `MARGIN_DAYS_RISKY` of clearing the quiet period, the same threshold `dry_run_report.py` already uses to sort) gets an amber band rather than being silently mixed in with the comfortable ones. Clicking the poster body, rather than the checkbox, opens the evidence drawer.

**Table** (default for TV Shows, where the evidence is per-episode and needs columns):

```
+---------------------------------------------------------------------------+
| [x] Title                  Size   Status   On disk  Watched  Last   Margin |
|---------------------------------------------------------------------------|
| [x] Some Series           24.1GB  Ended     62/62    62      184d    +170d |
| [ ] Another Series        18.6GB  Ended     40/40    40       96d     +82d |
| [ ] Third Series           9.8GB  Ended     13/13    13       19d      +5d | <- amber
+---------------------------------------------------------------------------+
```

Every column sortable. The `On disk` column shows enumerated episodes with files over aired episodes, computed from `episode_facts()`, never from `episodeCount`/`episodeFileCount`, which stay display-only and stay out of this table entirely to avoid anyone reading a number here and believing a decision was made from it.

**Evidence drawer.** Expanding a row or clicking a poster slides out a panel that is the `explain()` output rendered, and it is the trust-building surface of the whole application:

```
+---------------------------------------------------------------------------+
| Some Series                                          tvdb 123456   24.1 GB |
|---------------------------------------------------------------------------|
| SONARR                                                                     |
|   status            Ended (finished airing: yes)                           |
|   episodes enumerated  62 aired, 62 with a file, 0 never downloaded        |
|   not yet aired     0                                                      |
|                                                                            |
| TAUTULLI                                                                   |
|   <watcher>         62 distinct episodes, last viewed 2026-03-14           |
|   <other name>      11 distinct episodes, last viewed 2025-11-02           |
|                                                                            |
| THE SET DIFFERENCE                                                         |
|   on disk, never watched by <watcher>:   none                              |
|                                                                            |
| VERDICT  safe to remove                                                    |
|   all six conditions hold. 170 days past the 14-day quiet period.          |
|                                                                            |
|                                              [ Flag for removal ]          |
+---------------------------------------------------------------------------+
```

"THE SET DIFFERENCE" is named as its own section rather than folded into a verdict line, for the same reason `docs/IDEAS.md` wants the incomplete-series protection surfaced as a named reason in `explain()`: the thing that makes this tool worth trusting is the specific check it runs, and a user who cannot see that check running has no basis for trusting the answer over their own memory. On a blocked show this section lists the unwatched episode identifiers by name, which is the single most persuasive artifact the tool produces.

**Poster loading goes through the GUI's own server, never directly from the browser to Sonarr or Radarr.** Both services expose cover art at `/api/v3/MediaCover/{id}/poster.jpg`, which requires the API key. Letting the browser fetch that means putting the API key in page source or in a query string in the browser history. The GUI registers its own route that fetches server-side with the key in a header and streams the bytes back, caching to `state/covers/` (gitignored). The `images[].remoteUrl` field is a fallback only, and it reaches out to TheTVDB/TMDB from the browser, which is a small privacy leak and should be off by default.

---

## Tab: Blocked

Read-only, no checkboxes, no flag button. Everything that survived the cheap prefilter and was then blocked by the strict pass, each with its reasons listed. Sorted fewest-reasons-first, matching `dry_run_report.py`'s `blocked_sort_key`, because a show blocked by one thing is the one worth a second look and a show blocked six ways is not.

This tab exists because it is the strongest evidence the tool works. `scan()` already prints it under the heading "These are the ones a count-based rule would get wrong," and that framing is kept verbatim as the tab's subtitle. A user who sees a show they are midway through sitting in Blocked, with the exact unwatched episodes named, learns in one glance that the safe list is worth acting on. It also has no flag control at all, deliberately: there is no path from "I can see why this was blocked" to "remove it anyway" in this interface. Overriding a block is not a feature, and adding one would make every other screen meaningless.

---

## Tab: Hold Queue (write-capable)

The only screen that can delete. Visually distinct: the content pane gets a subtle warning-toned border and the tab header reads "Hold Queue" with the count.

```
+---------------------------------------------------------------------------+
|  HOLD QUEUE                                        scan is 3 days old  OK  |
|---------------------------------------------------------------------------|
|  These are flagged, not deleted. Nothing here is removed by a timer.       |
|  When the hold elapses you confirm a second time, or cancel.               |
|---------------------------------------------------------------------------|
|                                                                            |
|  ON HOLD                                                                   |
|  +----------------------------------------------------------------------+ |
|  | Some Series          TV    24.1 GB    flagged 3 days ago              | |
|  | hold ends in 4 days                                   [ Cancel ]      | |
|  | [####------] evidence at flag time: 62/62 watched, ended, +170d       | |
|  +----------------------------------------------------------------------+ |
|                                                                            |
|  READY TO REMOVE                                                           |
|  +----------------------------------------------------------------------+ |
|  | Some Film            Movie  12.1 GB   flagged 8 days ago              | |
|  | hold elapsed   re-checked just now: still safe        [ Cancel ]      | |
|  +----------------------------------------------------------------------+ |
|                                                                            |
|  1 item, 12.1 GB.  Type REMOVE to enable.   [______]   [ Remove 1 item ]  |
+---------------------------------------------------------------------------+
```

Behaviour that the layout encodes, specified fully in the backend design:

- **Two sections, never one list.** Items still inside their hold cannot be executed, and the control that would do it is not merely disabled for them, it is not rendered on their card at all.
- **A timer never deletes.** The hold elapsing moves a card from ON HOLD to READY TO REMOVE and nothing more. The second confirmation is always a human action.
- **Re-verification at execute time, shown before the button is live.** Entering the tab re-runs `verdict()` against fresh service data for every READY item. An item that no longer reads safe, because somebody started rewatching it during the hold, is moved back out with the new blocking reason displayed, and it cannot be executed in that session. This is reaper's played-since-approval re-check, borrowed deliberately.
- **A stale scan blocks execution entirely.** The header states the scan age; past the configured threshold the execute control is replaced by a "Re-scan before removing" button.
- **Typed confirmation, not a checkbox.** The word must be typed. This is the one place in the interface where friction is the feature.
- **Cancel is always available, always one click, and never confirms.** Reversal must be cheaper than action at every point.
- **Progress is per item, with the canary first.** Execution renders a line per item as it completes, smallest item first; a failure stops the run and leaves the remainder flagged rather than continuing.

---

## Tab: History

Append-only record of every executed removal: what, when, size reclaimed, and the evidence snapshot as it stood at flag time and at execute time. Read-only, no controls.

This is not a nicety. `docs/IDEAS.md`'s auto-delete proposal wants "a persisted record of each run so the streak is evidence rather than recollection," and notes that building the run log is worth doing regardless of whether auto-delete ever follows, because a shortlist that changes between runs for no reason is a bug nobody would currently see. This tab is that record, and building it now means the evidence for any future reliability bar starts accumulating from the first removal rather than from the day somebody decides to measure.

---

## Visual system

- **Dark by default**, single theme. No light mode, no toggle. The *arr suite is dark and so is every context this runs in.
- **Type:** system sans stack. Tabular numerals for every size, count and day figure so columns align and a 9 cannot be mistaken for a 4 in a scanned column.
- **Accent:** one green for safe, one amber for close-call and staleness, slate for blocked, red exclusively for execute. Four colours carrying meaning, no others.
- **Density:** compact. This is a table tool. Generous whitespace between sections, tight within them.
- **Motion:** none beyond Quasar defaults. AudioManager's pointer-tracking spotlight and mood-reactive theming are charming and belong in a music browser; they would be actively wrong in an interface whose job is to be believed about deletions.
- **Empty states say which kind of empty they are.** "Nothing is safe to remove" and "the scan has not been run" and "the watcher matches nobody so everything blocked" are three completely different states that all render as an empty list, and conflating them recreates the exact failure `_warn_if_watcher_unmatched()` was written to prevent, in a prettier form. Each has its own distinct empty state with its own wording and, where relevant, its own remedy button.

---

## Running it

`scripts/run-gui.bat` on Windows, following the existing `scripts/run.bat` thin-wrapper contract: check `config/config.json` exists and print the setup step if not, launch, `cmd /k` so the window survives. Host binds to `localhost` explicitly, not `0.0.0.0`, and this is asserted by a test rather than left to a default. Local-first means local-only until a separate design says otherwise, and `docs/IDEAS.md` already holds the mesh-network argument for the day that changes.

Hot-reload during development follows `AudioManager/gui/hot_reload.py`'s contract if it is wanted, but it is not part of this build.

---

## Out of scope for this design

Remote or hosted access, authentication, multi-user, and the mesh-network deployment. All held in `docs/IDEAS.md`, all deliberately excluded here. Also excluded: overriding a block, editing config from the GUI, and any bulk "select all safe items" control, which would make a fifty-item mistake exactly as cheap as a one-item one.
