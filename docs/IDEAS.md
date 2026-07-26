# Ideas & Future Work

Single source of truth for all pending work in this repo. Settled decisions and completed features -> `docs/HISTORY.md`.

---

## Current Focus

Nothing blocking. The tool is ready for its first hand-run by its owner: run `python src/broomarr.py --check` first, then `--all`. Movie support is the next real piece of work, and should not start until the TV side has actually been used against a live library.

---

## Pending - Main Work

*(Ordered by priority. Quick wins go FIRST within each tier - small, unblocked items before large/blocked ones. Items that are blocked or depend on other items go below their prerequisite.)*

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
