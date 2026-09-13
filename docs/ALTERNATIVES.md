# Alternatives considered

Before investing further in Broomarr, this is the check that nothing else already does the job: read your Sonarr/Radarr library, work out from *watch history* what is genuinely safe to delete, and either recommend or delete it. Written 2026-09-14, as the top-priority backlog item that gated further feature work.

Broomarr's own differentiators, restated so the table below can be checked against them:

1. **True per-episode enumeration.** It reads Sonarr's actual episode list and takes a set difference against watched episode identifiers - never a count, never a percentage, never trusting a media server's own aggregate.
2. **Unknown blocks.** Anything that can't be established (unreachable API, missing timestamp, no history) is a reason *not* to delete, never a skipped condition that silently passes.
3. **Never deletes anything itself.** No delete API call, no filesystem access, ever - it prints a shortlist and a human deletes manually through Sonarr.

## Comparison table

| Tool | Watched-status source | True per-episode enumeration? | Unknown blocks or skips? | Auto-deletes? | Stack / license | Maintenance |
|---|---|---|---|---|---|---|
| **Broomarr** (this repo) | Sonarr (episode list) + Tautulli | **Yes** - set difference, by design | **Blocks** - structural invariant | **Never** - print-only | Python stdlib, MIT | Active |
| [Maintainerr](https://github.com/jorenn92/Maintainerr) | Plex/Jellyfin/Emby | No - asks the media server, which only knows downloaded episodes | Skips (logs "value unavailable", item stays in the set) | Yes, after grace period | TypeScript, MIT | Active, v3.28.0 |
| [reaper](https://github.com/scythe-labs/reaper) | Tautulli + Seerr | Not confirmed either way; season-granular by design, not whole-show | **"Unknown never condemns"** - explicit, type-enforced | Off by default, opt-in to arm | Python/FastAPI + React, AGPL-3.0 | Pre-release, in development |
| [Reclaimerr](https://github.com/jessielw/Reclaimerr) | Jellyfin/Plex/Emby (+ Radarr/Sonarr optional) | Not stated in docs | Not stated | Yes, scheduled | Python + Svelte, GPL-3.0 | Active |
| [PrunArr](https://github.com/haijeploeg/Prunarr) | Tautulli (+ Overseerr requester tracking) | Not stated | Not stated | Staged - dry-run + confirmation prompt | Python, Apache-2.0 | Active |
| [Deleterr](https://github.com/rfsbraz/deleterr) | Tautulli | Not stated | Not stated | Yes, cron + dry-run option | Python, MIT | Active |
| [Purgeomatic](https://github.com/ASK-ME-ABOUT-LOOM/purgeomatic) | Tautulli watch stats | Not stated | Not stated | Yes, cron + dry-run | Python, GPL-3.0 | Active |
| [OCDarr](https://github.com/vansmak/ocdarr) | Plex/Jellyfin via Tautulli | Not stated | Not stated | Yes, deletes as it goes | Python | Active (beta) |
| [Plexorcist](https://github.com/stefanbc/Plexorcist) | Plex | Not stated | Not stated | Yes, with whitelist | Python, Apache-2.0 | Low activity |
| [sonarr-plex-cleaner](https://github.com/antifuchs/sonarr-plex-cleaner) | Plex | No - deletes fully-watched, fully-downloaded seasons only | Not stated | Yes | Rust, Apache-2.0 | Low activity |
| [Prunerr](https://github.com/helliott20/prunerr) | Plex/Jellyfin/Emby | Not stated | Not stated | Yes | TypeScript, MIT | Low activity |
| [Plex-Cleaner](https://github.com/ngovil21/Plex-Cleaner) | Plex | Not stated | Not stated | Yes | Python, MIT | **Archived (abandoned)** |
| [Usharr](https://github.com/nicholasodonnell/usharr) | Tautulli, movies only | N/A (Radarr, no episodes) | Not stated | Yes | TypeScript, GPL-3.0 | **Archived (abandoned)** |
| [Cleanarr](https://github.com/Cleanarr/Cleanarr) | - | - | - | - | GPL-3.0 | **Abandoned - README points to Maintainerr** |

## Not this category (checked and ruled out on purpose)

- **[Janitorr](https://github.com/Schaka/janitorr)** - close in spirit (Sonarr/Radarr, "leaving soon" staging, dry-run default) but explicitly does **not** use watch status as a deletion trigger at all: *"Janitorr does not delete items after they were watched."* It manages size/age instead. This is the exact condition Broomarr exists to check, so it doesn't compete on the actual question.
- **[Cleanuparr](https://github.com/Cleanuparr/Cleanuparr)** - download-queue housekeeper (stalled/malware torrents), not a library/watch-status tool. Easy name collision with "PrunArr" - confirmed a different project with a different purpose.
- **[Sortarr](https://github.com/Jaredharper1/Sortarr)** - read-only library analytics (missing media, mismatches), never deletes anything.
- **Watcharr, Wizarr, Recyclarr/TRaSH-Guides** - watch-list tracking, user invitations, and quality-profile config sync respectively. Different problem entirely.
- **MediaReaparr** - only found as a Docker Hub image with no discoverable source repo; couldn't be evaluated.

## Why build, not fork

**No tool found confirms all three of Broomarr's invariants together**, and most fail on the two that matter most for a partial library:

- Every tool that documents its watched-status method asks the **media server** (Plex/Jellyfin/Emby), the same gap `docs/References/DevContext.md` argues against - a half-downloaded series reads as fully watched once a later season is finished. None of the found projects' docs claim Sonarr/Radarr-side episode enumeration as ground truth the way Broomarr does; most simply don't say, which given the survivorship of "count-based" bugs (Broomarr shipped one itself, see `docs/HISTORY.md`) is a real gap, not a documentation oversight to assume away.
- Almost all of them **auto-delete**, most after a grace period, which is the class of risk Broomarr's read-only invariant exists to remove entirely. A wrong classification in an auto-deleting tool costs a file; in Broomarr it costs nothing until a human reads the list.
- Only one project - **reaper** - states an unknown-blocks safety principle as explicit and structural as Broomarr's ("unknown never condemns," enforced by the type system, deletion off until armed). It is the closest philosophical match found. It is also pre-release (in development on its main branch, no tagged release found), a much heavier stack (FastAPI + React vs. Broomarr's zero-dependency stdlib script), and does not confirm true per-episode enumeration either way in its docs.

**Verdict: keep building Broomarr.** Forking Maintainerr was already tried and rejected on the record (`docs/References/DevContext.md`), for reasons this research reconfirms - it's still the same architecture today (asks the media server, skips unresolvable rules). Forking any of the Tautulli-driven tools (PrunArr, Deleterr, Purgeomatic, Reclaimerr) would still require replacing their core watched-status computation with Sonarr-side enumeration, which is most of Broomarr's actual logic - there isn't a shortcut version of that fork. reaper is worth revisiting once it ships a tagged release and its docs confirm (or deny) per-episode enumeration; if it turns out to do everything Broomarr does plus a web UI, that would be a real reason to stop maintaining a second tool. Not there yet.

**Fragility check:** if reaper matures, confirms Sonarr-side per-episode enumeration, and ships a stable release before Broomarr's own web UI (`docs/IDEAS.md`) is built, the "keep building" verdict for the *UI* half specifically should be revisited - the CLI/verdict engine still has no confirmed substitute either way.
