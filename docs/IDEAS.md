# Ideas & Future Work

Single source of truth for all pending work in this repo. Settled decisions and completed features -> `docs/HISTORY.md`.

---

## Current Focus

Movie support is the next real piece of work. The first hand-run against the
real library is done - see `docs/HISTORY.md` (2026-08-21).

---

## Pending - Main Work

*(Ordered by priority. Quick wins go FIRST within each tier - small, unblocked items before large/blocked ones. Items that are blocked or depend on other items go below their prerequisite.)*

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
