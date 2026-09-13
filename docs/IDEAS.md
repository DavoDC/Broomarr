# Ideas & Future Work

Single source of truth for all pending work in this repo. Settled decisions and completed features -> `docs/HISTORY.md`.

---

## Current Focus

Building movie support (Radarr), the confirm-delete backend, and the GUI
together in one pass, by explicit decision - overriding the dependency order
below (movie support, then the confirm-delete UI, then the GUI skin). An Opus
subagent designs the combined brief first; a Sonnet subagent builds it against
that brief; a further Sonnet subagent then browser-tests the built GUI. See
the three entries below for the individual pieces this pass now does at once.

**The design is done and lives in `docs/design/`** (new folder, for proposals
about unbuilt work; `docs/References/DevContext.md` stays an account of what
exists). Three files: `reclaim-backend-design.md` (the Radarr join, the staged
hold-then-delete path and its seven interlocks, the empty-versus-unreadable
fix, and drafted replacement text for the invariant sections of `CLAUDE.md`,
`README.md` and `DevContext.md`), `gui-design.md` (layout, the NiceGUI stack
decision and what it costs, mutate-versus-observe sidebar grouping, tab
structure), and `build-brief.md` (the ordered, test-first build steps). The
open questions the entries below used to carry are answered there; what
remains below is the record of why each piece was wanted.

Three design decisions worth knowing without opening those files. **The
dependency invariant was re-scoped, not broken:** `src/broomarr.py` and the new
`src/reclaim.py` stay stdlib-only and the CLI keeps working with no
`pip install`; only `gui/` may depend on anything. **Deletion moved to its own
module** so the part that decides is not the part that acts, which is precisely
what Maintainerr does not do. **No timer ever deletes** - the hold elapsing only
makes an item offerable, and a human confirms a second time against a freshly
recomputed verdict.

The competitive landscape re-scan and its source-level audit are done - see
`docs/HISTORY.md` (both 2026-09-14 entries) and `docs/ALTERNATIVES.md`.
Verdict: keep building, but the reasons are practical (licence, stack weight,
problem size) rather than architectural - two other tools do read Sonarr's
episode list, and Broomarr's remaining technical claim is the set difference
specifically, not the data source.

---

## Pending - Main Work

*(Ordered by priority. Quick wins go FIRST within each tier - small, unblocked items before large/blocked ones. Items that are blocked or depend on other items go below their prerequisite.)*

---

**Run reaper in dry-run mode against the real library, once, before the next planning round.** The source audit (`docs/ALTERNATIVES.md`, `docs/HISTORY.md` 2026-09-14) found that reaper is the first tool in the survey not disqualified on architecture: it reads Sonarr's episode list as its denominator, rejects `episodeCount`/`totalEpisodeCount` for Broomarr's own reasons, and its unknown-handling is enforced by the type system. The case for maintaining Broomarr now rests partly on an assumption nobody has tested - that reaper's shortlist would be worse than Broomarr's. It ships with `dry_run` on by default plus a host-level environment variable that must be set before any mutating call, so a read-only trial costs nothing but setup time. Run it, compare its shortlist against Broomarr's on the same library, and record the result here. If it is as good, the honest conclusion is that Broomarr's remaining value is exactness and legibility, not capability - which is a fine reason to keep it, but a different one from the reason currently written down.

---

**Audit `episode_facts()` for the empty-vs-unreadable collapse.** Designed, not
yet built - the fix is specified in `docs/design/reclaim-backend-design.md`
section 2 and is **step 1** of `docs/design/build-brief.md`, promoted to the
front of that build because the same pass attaches a delete button to
`verdict()`'s output and shipping a delete path over a known fail-open in the
function feeding it would be indefensible. The design confirms the hole is
live: a literal `[]` from Sonarr's episode endpoint raises nothing, so
`verdict()`'s exception handler never fires and all three downstream falsy
checks no-op into a pass. Fix is three independent changes (a named
`UnreadableFacts` raise, an `on_disk_eps` that is `None` rather than empty when
unestablished, and a `verdict()` block on an empty on-disk set even after a
successful read), any one of which alone would prevent it. Original note
follows. Small, safety-relevant, and prompted by reaper's handling of the same problem. reaper keeps an `episodes_read` flag beside its episode map and types the map `Mapping | None` specifically so an empty map from a failed Sonarr call cannot impersonate a show with no episodes ("a missing episode map is `None`, never `{}`"). Broomarr's verdict is a set difference, `on_disk_eps - watched_eps`, and an empty `on_disk_eps` yields an empty difference - which reads as "nothing unwatched on disk," which is a *pass*. That is a fail-open hiding inside a fail-closed design. `verdict()` does append a block reason on an exception reading the episode list, so the live path is probably fine; the point is that "probably" is the wrong standard for this class of defect and there should be a test asserting that an empty or unreadable episode list blocks rather than passes. Check every path that can produce an empty `on_disk_eps`, not just the exception one.

---

**Surface the incomplete-series protection as a named reason in `explain()`.** reaper shows an operator "episodes are missing" as an explicit protection reason rather than leaving it implicit in the outcome. Broomarr has the same fact and the better version of it (enumerated, not counted) but does not always say so in as many words. Cheap, and it is the kind of thing that makes a shortlist trustworthy to read.

---

**FUTURE OPTION, NOT A DECISION: opt-in auto-delete, armed only after a demonstrated reliability bar.** This is recorded as a proposal under consideration, and it remains one: the human-confirmed path being designed now is deliberately *not* this, and nothing in that design arms anything. The paragraph below said "Broomarr does not delete today and `CLAUDE.md` and `README.md` are accurate as written." That stops being true when `docs/design/build-brief.md` step 5 lands; the invariant rewrite it asked for as a prerequisite is drafted in `docs/design/reclaim-backend-design.md` section 5, and the `DevContext.md` argument it asked to be answered explicitly is answered in section 4. So the prerequisite this entry named is satisfied by the confirm-flow work, not by this entry - which makes the ordering note at the end of it more important, not less: **the confirm flow is the better answer to the same friction and it costs no automation; auto-delete is only worth reconsidering if that turns out not to be enough.** One piece of it is being built regardless, per its own argument below: the History tab is the persisted per-run record that would make any future reliability streak evidence rather than recollection.

The case for opening it: the media is re-downloadable, so the cost of a wrong deletion is usually bandwidth and inconvenience rather than loss, and the manual step is the main friction in actually using the tool. The case against a blanket flip: re-downloadability is not uniform (out-of-print, unusual cuts, anything personal), a wrong deletion is typically noticed weeks later by the person who wanted to watch it, and a *systematic* fault removes fifty shows rather than one, which is expensive even at a low per-item cost. See `docs/ALTERNATIVES.md`, "Are these the right axes?", for the full reasoning.

That shape of risk points at a narrow, staged design rather than a `--delete` flag:

- **Soft delete, never hard.** The armed path unmonitors the series in Sonarr and moves its files to a holding location, or flags them for removal on a timer. Actual deletion happens after a hold long enough for someone to notice - a month, not a day. Nothing is armed that cannot be undone by moving files back.
- **Arm per scope, never globally.** A tag, a specific set of titles, or a single library at a time. The protected-media exclusion list below is a hard prerequisite, not a companion feature - there must be no way to arm before exclusions exist.
- **Caps that abort rather than truncate.** A run that exceeds N items or M bytes stops entirely and reports, rather than deleting the first N. Truncating lets sort order pick the victims.
- **Canary first.** Smallest item, alone, verified, before anything else in the run proceeds. A broken path mapping then costs one file. (This and the previous two are reaper's design, borrowed deliberately - see `docs/ALTERNATIVES.md`.)
- **Two independent switches.** An in-config arm flag and a host-level environment variable, so no single bug or bad config can arm the tool.

"Proven reliable enough to arm" should mean something checkable, not a feeling. A defensible bar: **thirty consecutive days of scheduled dry runs whose shortlists were reviewed, with zero entries a human rejected**, plus a persisted record of each run so the streak is evidence rather than recollection. One rejection resets the count. The streak should be per-scope, since a tool that is reliable on one library has demonstrated nothing about another. Note that this bar is itself a feature to build - run logging and shortlist-diffing between runs - and it is worth building regardless of whether auto-delete ever follows, because a shortlist that changes between runs for no reason is a bug nobody would currently see.

Ordering: this comes after movie support, after the protected-media exclusion list, and after the web UI's confirm flow has been used in anger for a while. The confirm flow is the better answer to the same friction and it costs no invariant; auto-delete is only worth considering if that turns out not to be enough.

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

**Movie support via Radarr.** Designed in
`docs/design/reclaim-backend-design.md` section 1; build steps in
`docs/design/build-brief.md` step 2. The design settles the open questions this
entry left: the join key is `(normalised_title, year)` rather than title alone,
since remakes sharing a title are the norm in film but sharing a title *and* a
year is not; `movie_facts()` returns `MovieFacts | None` where `None` means
"could not establish", never "there is nothing"; Radarr is **optional**, so a
config without it stays a valid TV-only install; and `MovieLibrary.verdict()`
deliberately takes no `deep` parameter, because the bulk `/api/v3/movie`
response already carries every field the verdict needs and a parameter that is
always the same value is a place for a future bug to hide. The design also
names the movie side's weakest point, which this entry did not anticipate:
a partial view is the *entire* watch signal for a film, where on the TV side it
is harmless because the set difference still names the other episodes - so
Tautulli's `watched_status >= 0.5` threshold is load-bearing on the movie side
in a way it is not on the TV side. Original note follows. Radarr has no
episode concept, so the join is simpler than the Sonarr side: one film either
has a file or does not, and Tautulli's `media_type=movie` history gives a
single watched/not-watched fact per user instead of a per-episode set. The
"unknown blocks" rule and the read-only invariant both carry over unchanged -
a movie verdict is just a smaller version of `Library.verdict()`. Note the
lesson from the TV side before starting: the join must be over identifiers,
and for movies that means a rating key or title match per film, never a count
of how many films somebody watched.

---

**Web UI for user-confirmed deletion.** Designed in
`docs/design/reclaim-backend-design.md` section 3 (the state machine, the seven
interlocks, the exact Sonarr and Radarr delete calls) and section 4 (the
answer to `DevContext.md`'s "why it cannot delete", on that argument's own
terms); interface in `docs/design/gui-design.md`; build steps in
`docs/design/build-brief.md` steps 3 and 4. The invariant rewrite this entry
anticipated is drafted verbatim in `reclaim-backend-design.md` section 5, for
`CLAUDE.md`, `README.md` and `DevContext.md`, to be applied in the same commit
as the code that makes it true. Two design choices the entry left open: the
staging is a hold queue with a second typed human confirmation rather than a
soft delete to a holding folder, because the hold already provides the
reversal window and a file-moving variant would mean Broomarr gaining
filesystem and path-mapping awareness (much the larger change); and the write
path lives in a new `src/reclaim.py` so `src/broomarr.py` keeps its literal
read-only property and the part that decides is not the part that acts.
Original note follows. Broomarr's invariant is that it never deletes - `verdict()` only produces a reason to block or a candidate to remove, and every existing entry point is read-only. This idea does not weaken that invariant in code; it adds a human in the loop who confirms each removal. A user knows what they've actually watched better than any heuristic does, so the UI's job is to surface `verdict()`'s candidates sorted by watch percentage, let a user tick the ones they recognise as watched, and only then call the one delete path that gets added, on their confirmation, not the algorithm's. This is the mirror image of a media request tool, which lets people ask for additions - here they retire what they've finished.

Build and use it locally first, against a real library, before any of it is network-reachable. If it's ever hosted for remote access, that deserves its own design-time review - a separate, narrower artifact from the local tool rather than the same code with a flag flipped, login required, and no bulk enumeration of the library from the confirm screen. Deletion itself should stay staged (flag for removal, hold, then actually delete) rather than immediate, so a wrong tap doesn't cost a file. None of this starts before movie support (Radarr) lands and the TV side has had a real hand-run, per Current Focus above. (One-off override in progress: this pass builds movie support, this UI's delete backend, and the GUI skin below together, by explicit decision - not a change to the default ordering for future work.)

**When it does become remote-reachable, reach it over a private mesh network rather than a port forward.** A mesh VPN such as Tailscale, or its self-hosted equivalent Headscale, binds the app to a private address shared only between enrolled devices. There is no open port for a scanner to find, and someone who is not already on the network cannot reach the login page at all, let alone probe it. The free tier covers a household-sized set of devices, and node sharing invites one specific person to one specific service without handing them the rest of the network. It also replaces the certificate problem: a mesh network encrypts the link without anyone generating a self-signed certificate that every client then has to be told to trust.

The reason to prefer this over a port forward is sharper for a tool like this one than for the popular self-hosted applications it sits alongside. **A hand-written app is a worse thing to expose than a widely used community one.** A popular open-source project has many users, a security contact, published advisories and outsiders who report bugs in it, so when it turns out to be vulnerable a fix usually exists and the task is to have applied it. A tool written by one person for one library has none of that: no one else is reviewing its session handling or its input parsing, no advisory will ever be published for it, and the first person to find a flaw in it will be the one exploiting it. "Keep it patched" is not a strategy for software with no upstream. Given that this particular app is the only entry point that will ever hold a delete path, the asymmetry is worth taking seriously: the worst case is not a leaked watch history, it is someone else driving the deletion.

The same argument generalises beyond this repo. Anything self-written and reachable from outside the house belongs behind the mesh network, and putting one service there is most of the work of putting all of them there, so it is worth doing once and reusing rather than deciding per app.

---

## Lower Priority / Future

*(Ordered by size - smaller/quicker first. These are not urgent but worth doing eventually.)*

---

**Recommendation: land protected-media exclusions before the web UI's confirm screen ships.** **This recommendation is being overridden by the combined pass in Current Focus, and that is a real, named gap rather than an oversight.** The confirm screen is being built without exclusion support, so a protected title will appear as a normal candidate and the only thing standing between it and removal is the human reading the list - which is, to be fair, the entire premise of the confirm flow, and the hold queue gives a week to catch it. But the risk this entry identified is genuine and is not mitigated by the design, only survived by it. Build exclusions next, before the first real removal if practical. Of the three items below, the exclusion list is the smallest and it gates the deletion-confirmation UI in the "Pending - Main Work" section above - a confirm screen with no exclusion support could surface a protected title as a normal candidate. Do this one first, the GUI redesign second (cosmetic, no safety dependency), and treat the remote-access idea as exploratory since it depends on constraints on a specific device that need confirming before any design work starts.

---

**Protected-media exclusion list.** Some titles (a specific rewatch favourite, say) and some whole categories (anime as a category, for example) should never be surfaced as a deletion candidate at all, regardless of watch state - not "warn and let a human override," but excluded from `verdict()` before a candidate is ever produced. This wants two levels: an exact-title (or stable-ID) exclude list in `config.json`, and a category/genre-level exclude flag, since Sonarr exposes genre/tag metadata per series. Needs a decision on whether the category match is a hardcoded genre string or a configurable list, and whether exclusion is silent (title never appears anywhere) or shows up in `explain()` as "excluded, not evaluated" for transparency.

---

**GUI redesign closer to Sonarr/Radarr/Overseerr's look.** Designed in
`docs/design/gui-design.md`; build steps in `docs/design/build-brief.md` step
4. The "check an existing local repo's frontend first" instruction below was
followed: AudioManager's `docs/References/GUI-Architecture.md` supplied the
sidebar-tab layout, the mutate-versus-observe grouping, the rejected
auto-run-on-launch pattern (read cached state, show staleness, offer a manual
Re-run) and the "GUI is not a replacement for CLI" principle, all adopted. The
one judgment call that entry could not have anticipated: **NiceGUI is a new
dependency and `CLAUDE.md`'s stdlib-only invariant had to be re-scoped rather
than quietly broken** - the boundary is now drawn at the directory, with
`src/` staying dependency-free and testable on a bare Python install and only
`gui/` allowed to depend on anything, enforced by a test. Reasoning and the
rejected alternatives are in the design doc's stack section. Original note
follows. Broomarr's own web UI (once the user-confirmed deletion UI above exists) could follow the visual pattern of the *arr suite or Overseerr rather than a bespoke layout - dark theme, poster-grid browsing, sortable tables. Check whether an existing local repo's frontend (an audio-library manager app on this machine) has reusable layout/component patterns before building from scratch, per the pattern-copy research approach. Depends entirely on the web UI existing first (see "Web UI for user-confirmed deletion" above) - this is a skin on that, not a separate feature. (One-off override in progress, per Current Focus above: built in the same pass as the confirm-delete UI, not after it.)

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
