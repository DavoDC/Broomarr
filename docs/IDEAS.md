# Ideas & Future Work

Single source of truth for all pending work in this repo. Settled decisions and completed features -> `docs/HISTORY.md`.

---

## Current Focus

The combined build pass (movie support, the reclaim backend, the GUI, and
the documentation rewrite) described in `docs/design/build-brief.md` is
done - see `docs/HISTORY.md`'s 2026-09-14 entries for what was built and
where it diverged from the design. The one gap that pass knowingly left
open, named by its own entries at the time: **the protected-media
exclusion list does not exist yet**, so a confirm screen with no
exclusion support can surface a protected title as a normal candidate,
survived only by the human reading the hold queue and the week-long hold.
That is the next thing worth building, before the first real removal
against the live library if practical - see "Protected-media exclusion
list" below.

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

## Lower Priority / Future

*(Ordered by size - smaller/quicker first. These are not urgent but worth doing eventually.)*

---

**This recommendation was overridden, knowingly, and the gap it named is now live.** The confirm screen shipped without exclusion support: a protected title appears as a normal candidate today, and the only thing standing between it and removal is the human reading the hold queue and the week-long hold - which is, to be fair, the entire premise of the confirm flow, but the risk this entry identified is real and is only survived by the design, not mitigated by it. Build exclusions next, before the first real removal against the live library if practical - see "Current Focus" above.

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
