# History

---

## 2026-07-26 - README rewrite: state the conditions, not sample output

Commit `6c0471a`. Dropped the block of example terminal output from the README - it
goes stale the moment the CLI's output changes shape, nothing tests it against
reality, and a reader has no way to check it either way. Replaced it with the six
conditions in plain language, laid out as a table, and a direct answer to "is this a
rule engine" (no, and why not). Field-level implementation detail that used to live in
the README moved out to `CLAUDE.md` instead, following the routing split: README is
what a new reader needs to decide whether to use the tool, `docs/DESIGN.md` carries
the design argument, `CLAUDE.md` carries the implementation detail Claude needs when
touching the code.

## 2026-07-26 - scripts/run.bat launcher

Commit `0cf8668`. Windows entry point for people who would rather not type the
`python` invocations by hand. Prompts for scan-whole-library vs explain-one-show,
checks `config/config.json` exists first and prints the setup step if it does not
(instead of letting `broomarr.py` fail with a raw traceback), and keeps the window
open on completion (`cmd /k`) so the result is still on screen after the script
finishes. `--no-pause` skips the prompt (defaults to a full scan) and exits cleanly,
for anyone who wants to call it from something else.

## 2026-07-26 - Fixed: watched-vs-on-disk check compared counts, not identities

Commit `d52368d`. `verdict()` decided whether the watcher had seen everything on disk
by comparing `len(watched_eps)` to `stats["episodeFileCount"]` - two integers, never
which episodes they actually were. Equal counts with different identities read as
safe: a watcher who had seen S01E01 through E10 while S02E01 through E03 sat on disk
unwatched produced two equal numbers and a pass. `episodeFileCount` is also the count
`docs/DESIGN.md` already argues against on separate grounds, so the one check whose
entire thesis is "never decide from a count" was itself deciding from one.

Fixed by having `episode_facts()` return the on-disk `(season, episode)` identifiers
as well as the missing/upcoming lists it already returned, and having `verdict()`
take a set difference against the watched set instead of comparing lengths. Both
sides are coerced to `int` first (`_to_int()`), because Tautulli returns these as
strings in some API versions and an uncoerced mismatch would silently join to
nothing, blocking every show rather than the wrong one - safe, but useless, and
indistinguishable from the check working. The shallow count-based fallback in the
cheap prefilter was deleted rather than patched: the prefilter is only safe because
it is structurally a weaker version of the strict check, the same function with the
episode-list conditions skipped, never an approximation of them. Regression tests
cover the count-agrees-but-identities-differ case and the prefilter-never-stricter
invariant. `docs/DESIGN.md` gained a third trap section on why a count comparison is
unsafe even without a hidden filter involved.
