# Ideas & Future Work

Single source of truth for all pending work in this repo. Settled decisions and completed features -> `docs/HISTORY.md`.

---

## Current Focus

Movie support is the next real piece of work. The first hand-run against the
real library is done - see `docs/HISTORY.md` (2026-08-21). The competitive
landscape re-scan is also done - see `docs/HISTORY.md` (2026-09-14) and
`docs/ALTERNATIVES.md` - verdict: keep building.

---

## Pending - Main Work

*(Ordered by priority. Quick wins go FIRST within each tier - small, unblocked items before large/blocked ones. Items that are blocked or depend on other items go below their prerequisite.)*

---

**HIGHEST PRIORITY - blocking, do first: audit and enrich `docs/ALTERNATIVES.md`, resolve every "Not stated" cell against real source, and re-open the auto-delete question.** Two things prompted this: (1) `docs/ALTERNATIVES.md` was written from README/doc claims only - several tools' rows say "Not stated" for enumeration and unknown-handling because their public docs don't say, not because the code was checked; (2) the comparison table implicitly treats "auto-deletes" as a strike against a tool, on the assumption that a wrong deletion is costly - worth re-examining given that this media is easily re-downloadable, which changes the actual cost of a wrong auto-delete. Plan, in order:

1. Clone the still-active alternatives plus `reaper` into `C:\Users\David\GitHubRepos\NOT_MY_REPOS` (Maintainerr, Reclaimerr, PrunArr, Deleterr, Purgeomatic, OCDarr, reaper - skip the low-activity/archived/abandoned ones, they're not credible fork candidates).
2. Read each clone's actual watched-status/deletion logic and replace every "Not stated" cell in the comparison table with a real, source-checked answer.
3. Only then re-judge: is "auto-deletes" still the right thing to penalize a tool for, given re-downloadable media lowers the cost of a wrong call? Should Broomarr itself gain an opt-in auto-delete mode once it's proven reliable against a real library for a while? This is a real option now, not ruled out by default - but it changes the "never deletes anything itself" invariant in `CLAUDE.md` and `README.md`, so it needs to land as its own deliberate decision, not a quiet edit alongside the doc enrichment.
4. Is `reaper` (closest philosophical match, but pre-release and does not confirm per-episode enumeration in its docs) worth forking instead of continuing to build Broomarr from scratch, once its actual code is checked?
5. Are "true per-episode enumeration" and "unknown blocks" still the right columns to be comparing on, or does the redownloadable-media framing change which properties actually matter?

Findings and any revised verdict go into `docs/ALTERNATIVES.md` itself (and `docs/HISTORY.md` once settled) - this entry is the task only.

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

**Movie support via Radarr.** Radarr has no
episode concept, so the join is simpler than the Sonarr side: one film either
has a file or does not, and Tautulli's `media_type=movie` history gives a
single watched/not-watched fact per user instead of a per-episode set. The
"unknown blocks" rule and the read-only invariant both carry over unchanged -
a movie verdict is just a smaller version of `Library.verdict()`. Note the
lesson from the TV side before starting: the join must be over identifiers,
and for movies that means a rating key or title match per film, never a count
of how many films somebody watched.

---

**Web UI for user-confirmed deletion.** Broomarr's invariant is that it never deletes - `verdict()` only produces a reason to block or a candidate to remove, and every existing entry point is read-only. This idea does not weaken that invariant in code; it adds a human in the loop who confirms each removal. A user knows what they've actually watched better than any heuristic does, so the UI's job is to surface `verdict()`'s candidates sorted by watch percentage, let a user tick the ones they recognise as watched, and only then call the one delete path that gets added, on their confirmation, not the algorithm's. This is the mirror image of a media request tool, which lets people ask for additions - here they retire what they've finished.

Build and use it locally first, against a real library, before any of it is network-reachable. If it's ever hosted for remote access, that deserves its own design-time review - a separate, narrower artifact from the local tool rather than the same code with a flag flipped, login required, and no bulk enumeration of the library from the confirm screen. Deletion itself should stay staged (flag for removal, hold, then actually delete) rather than immediate, so a wrong tap doesn't cost a file. None of this starts before movie support (Radarr) lands and the TV side has had a real hand-run, per Current Focus above.

**When it does become remote-reachable, reach it over a private mesh network rather than a port forward.** A mesh VPN such as Tailscale, or its self-hosted equivalent Headscale, binds the app to a private address shared only between enrolled devices. There is no open port for a scanner to find, and someone who is not already on the network cannot reach the login page at all, let alone probe it. The free tier covers a household-sized set of devices, and node sharing invites one specific person to one specific service without handing them the rest of the network. It also replaces the certificate problem: a mesh network encrypts the link without anyone generating a self-signed certificate that every client then has to be told to trust.

The reason to prefer this over a port forward is sharper for a tool like this one than for the popular self-hosted applications it sits alongside. **A hand-written app is a worse thing to expose than a widely used community one.** A popular open-source project has many users, a security contact, published advisories and outsiders who report bugs in it, so when it turns out to be vulnerable a fix usually exists and the task is to have applied it. A tool written by one person for one library has none of that: no one else is reviewing its session handling or its input parsing, no advisory will ever be published for it, and the first person to find a flaw in it will be the one exploiting it. "Keep it patched" is not a strategy for software with no upstream. Given that this particular app is the only entry point that will ever hold a delete path, the asymmetry is worth taking seriously: the worst case is not a leaked watch history, it is someone else driving the deletion.

The same argument generalises beyond this repo. Anything self-written and reachable from outside the house belongs behind the mesh network, and putting one service there is most of the work of putting all of them there, so it is worth doing once and reusing rather than deciding per app.

---

## Lower Priority / Future

*(Ordered by size - smaller/quicker first. These are not urgent but worth doing eventually.)*

---

**Recommendation: land protected-media exclusions before the web UI's confirm screen ships.** Of the three items below, the exclusion list is the smallest and it gates the deletion-confirmation UI in the "Pending - Main Work" section above - a confirm screen with no exclusion support could surface a protected title as a normal candidate. Do this one first, the GUI redesign second (cosmetic, no safety dependency), and treat the remote-access idea as exploratory since it depends on constraints on a specific device that need confirming before any design work starts.

---

**Protected-media exclusion list.** Some titles (a specific rewatch favourite, say) and some whole categories (anime as a category, for example) should never be surfaced as a deletion candidate at all, regardless of watch state - not "warn and let a human override," but excluded from `verdict()` before a candidate is ever produced. This wants two levels: an exact-title (or stable-ID) exclude list in `config.json`, and a category/genre-level exclude flag, since Sonarr exposes genre/tag metadata per series. Needs a decision on whether the category match is a hardcoded genre string or a configurable list, and whether exclusion is silent (title never appears anywhere) or shows up in `explain()` as "excluded, not evaluated" for transparency.

---

**GUI redesign closer to Sonarr/Radarr/Overseerr's look.** Broomarr's own web UI (once the user-confirmed deletion UI above exists) could follow the visual pattern of the *arr suite or Overseerr rather than a bespoke layout - dark theme, poster-grid browsing, sortable tables. Check whether an existing local repo's frontend (an audio-library manager app on this machine) has reusable layout/component patterns before building from scratch, per the pattern-copy research approach. Depends entirely on the web UI existing first (see "Web UI for user-confirmed deletion" above) - this is a skin on that, not a separate feature.

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
