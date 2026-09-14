# Broomarr

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/G2G31WKOCN)

**Find the TV shows and movies you can safely delete, without ever suggesting one somebody was halfway through.**

Broomarr reads your Sonarr library (and Radarr, if you have it configured) and your Tautulli watch history, and answers one question per show or movie: has the person who was watching this actually finished it, and is there genuinely nothing left for them to watch? It prints a shortlist. You delete through Sonarr or Radarr yourself.

## What it checks

Broomarr makes **one decision** - safe to delete, or not - and on the TV side it applies **six conditions, all of which must hold**. It is not a rule engine and there is nothing to configure beyond who the watcher is and how long the quiet period lasts. That is deliberate: a rule you can express is a rule you can express wrongly.

A show is safe to delete only when all six are true:

| # | Condition | It blocks when |
|---|---|---|
| 1 | The watcher has history for the show | they never started it |
| 2 | Every episode on disk has been watched by them | any episode sitting there unwatched |
| 3 | Every episode that has aired is on disk | a season was never fetched |
| 4 | No episodes are still to be broadcast | more are coming |
| 5 | Sonarr says the series has finished airing | it is still running |
| 6 | Nobody has touched it recently | inside the quiet period, 14 days by default |

Condition 6 is worth saying out loud: **watching something recently blocks deletion.** It never counts towards it.

A movie is a simpler version of the same idea, since there is no season or episode structure to check: it must have a file on disk, Radarr must report it as released (not announced or in cinemas), the watcher's Tautulli history for it must show a completed view (a partial view blocks - for a film that partial view is the entire watch signal, there is no per-episode set difference to fall back on), and that view must sit outside the quiet period. The join between Radarr and Tautulli is on (title, year), never title alone, and two Radarr entries that happen to share both are treated as indistinguishable and both blocked rather than guessed at.

## The two ideas that make it different

**An unknown value blocks.** Rule engines usually skip a condition they cannot evaluate, which switches a safety check off while the configuration still reads as correct. Here, anything that cannot be established is a reason not to delete. No watch history, an unreachable Sonarr, a missing timestamp - all block.

**No decision is ever made from a count.** Condition 2 is not "watched 10, and 10 are on disk". It is a comparison of which episodes, one by one. Counts hide things: Sonarr's own `episodeCount` and `episodeFileCount` both exclude unmonitored episodes, so they can agree while an entire season is missing. Two numbers agreeing is not corroboration when both carry the same hidden filter.

Together these are why Broomarr asks Sonarr rather than the media server. Plex, Jellyfin and Emby can only tell you about episodes that were downloaded, so a half-fetched series reports as fully watched the moment somebody finishes a later season. Sonarr knows the real episode list. `docs/References/DevContext.md` makes the full argument, including a fair account of why [Maintainerr](https://github.com/jorenn92/Maintainerr) was used first and then replaced.

## Broomarr never deletes on its own

There is no schedule, no daemon and no timer that can delete anything. Nothing is ever removed by a run nobody watched, because there are no runs nobody watched: if you do not open Broomarr, nothing happens.

What it can do, since you asked for it in the interface, is carry out a removal **you confirm twice, days apart**. You flag a candidate; it sits in a hold queue for a week; when the hold elapses Broomarr recomputes the whole verdict against live data, tells you if anything changed while it waited, and only then offers you a confirmation you have to type. Cancelling is one click at any point, and it never asks you to confirm the cancel.

Around that sit seven interlocks: it refuses to act on a stale scan, it re-verifies every item against live Sonarr, Radarr and Tautulli at the moment of execution, it aborts rather than truncates when a run exceeds its caps, it deletes the smallest item first and checks that it worked before touching anything else, it re-reads each item immediately before removing it, and it writes the record after each removal rather than at the end. A tool that deletes needs to be right on every run; this one only ever runs while you are watching it, and it spends that run trying to talk you out of it.

The decision engine cannot delete. `src/broomarr.py` makes no write call to anything and holds no `--delete` flag; the removal path is a separate module (`src/reclaim.py`) you have to deliberately reach through the GUI's Hold Queue tab. The part that decides is not the part that acts, and that is enforced by the code rather than promised by this paragraph.

## Setup

Python 3.8 or newer. No dependencies, standard library only.

```
git clone https://github.com/<you>/Broomarr.git
cd Broomarr
copy config\config.example.json config\config.json
```

Fill in `config/config.json`, which is gitignored so your keys stay local:

| Field | Where to find it |
|---|---|
| `sonarr_url`, `sonarr_api_key` | Sonarr, Settings - General - API Key |
| `tautulli_url`, `tautulli_api_key` | Tautulli, Settings - Web Interface - API Key |
| `radarr_url`, `radarr_api_key` (optional) | Radarr, Settings - General - API Key. Set both to enable movies, or leave both out - one without the other is refused at startup rather than silently half-working. |
| `watcher` | the Tautulli friendly name whose viewing decides, matched case-insensitively as a substring |
| `quiet_days` | how long a show must be left alone, default 14 |

## Running it

Run this first. It confirms every configured service answers and that your `watcher` matches a real Tautulli name, without scanning anything:

```
python src/broomarr.py --check
```

Then:

```
python src/broomarr.py --all              scan TV, and movies too if Radarr is configured
python src/broomarr.py --movies           scan movies only (needs radarr_url/radarr_api_key)
python src/broomarr.py "Some Show"        explain one show in full
```

On Windows, `scripts\run.bat` prompts for the mode and keeps the window open.

For the GUI - Dashboard, TV Shows, Movies, Blocked, and the Hold Queue where a flagged item can actually be removed after its hold elapses - run:

```
python -m gui.main
```

or `scripts\run-gui.bat` on Windows. It binds to `127.0.0.1` only by default and opens at `http://localhost:8472`. It never scans on launch; press Re-scan on the Dashboard once it is open.

### Giving someone else access

By default the GUI has no login at all, since it only ever listens on `127.0.0.1` - nothing outside your own machine can reach it. If you plan to make it reachable beyond that (for example through a private tunnel to one specific other person), set these in `config/config.json` first:

| Field | What it does |
|---|---|
| `gui_users` | A map of username to `{"password_hash": ..., "role": "admin" or "viewer"}`. Leave empty or omit it to keep the GUI login-free. |
| `gui_storage_secret` | A long random string used to sign the session cookie. Required once `gui_users` is non-empty. |
| `gui_host`, `gui_port` | Where the GUI listens. Default to `127.0.0.1:8472`. Never set `gui_host` to `0.0.0.0` - that exposes it to your whole local network, not just the one path in you intended. |

Generate a password hash rather than typing a plaintext password into config.json:

```
python scripts/set-gui-password.py
```

It prompts for a password (never echoed, never written to any log) and prints a `gui_users` snippet to paste in. A `viewer` account can see everything but cannot flag, cancel or remove anything, at the point each of those actions runs, not only in which buttons the page happens to show. `scripts/check-auth-enforced.py` sends unauthenticated requests at a running GUI and confirms every route redirects to `/login` or refuses instead of serving app content.

The single-show form prints what Sonarr holds, which episodes were never downloaded, who watched how many and when, and every reason the show is or is not a candidate. Reach for it whenever you disagree with the scan - it is the same six conditions, shown working.

## Tests

```
python -m pytest tests -q
```

The suite is mostly deletions that must not happen, including regression fixtures for the two failures that shaped the design: a series whose counts agree while a whole season is missing, and one where the watcher's episode count matches the number on disk but they are not the same episodes.

## Scope

TV and movies. The movie join is a simpler version of the same idea: Radarr has no episodes, so one film either has a file or does not, and the join is on title and year rather than a per-episode set. Radarr is optional - a config without it is a valid TV-only install.

The decision engine (`src/broomarr.py`) still reads from Sonarr, Radarr and Tautulli and writes to none of them. The optional reclaim path (`src/reclaim.py`, reached through the GUI) keeps its own local state under `state/` (gitignored - a hold queue and a removal history) and, only after two confirmations days apart, deletes through the same APIs Sonarr's and Radarr's own UIs use.

**Status:** Active development. TV and movie support, a local web interface, and a confirm-then-hold removal flow.

## Licence

MIT.
