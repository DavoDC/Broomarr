# Ideas & Future Work

Single source of truth for all pending work in this repo. Settled decisions and completed features -> `docs/HISTORY.md`.

---

## Current Focus

TV support is complete. Movie support via Radarr is the next thing planned - see README Scope section.

---

## Pending - Main Work

*(Ordered by priority. Quick wins go FIRST within each tier - small, unblocked items before large/blocked ones. Items that are blocked or depend on other items go below their prerequisite.)*

---

**Movie support via Radarr.** README already states this is next. Radarr has no
episode concept, so the join is simpler than the Sonarr side: one film either
has a file or does not, and Tautulli's `media_type=movie` history gives a
single watched/not-watched fact per user instead of a per-episode set. The
"unknown blocks" rule and the read-only invariant both carry over unchanged -
a movie verdict is just a smaller version of `Library.verdict()`.

---

## Lower Priority / Future

*(Ordered by size - smaller/quicker first. These are not urgent but worth doing eventually.)*

---

**Multiple watchers per show, not one named watcher.** `config.json` currently
takes a single `watcher` string matched case-insensitively. Households where
more than one person needs to have finished a show before it is safe to
remove would need the verdict to require all configured watchers, not just
one - matters for shared libraries, not solo ones.

---

**Config validation for `sonarr_url` / `tautulli_url` reachability at startup.**
`load_config` currently only checks that the required keys are present, not
that the URLs are well-formed or reachable. A clear early error beats a
confusing stack trace from `urllib.request` deep inside a scan.

---

## See Also

- `docs/HISTORY.md` - completed features, settled design decisions, parked ideas
