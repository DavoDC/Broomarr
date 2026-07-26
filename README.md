# Broomarr

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/G2G31WKOCN)

**Find the TV shows you can safely delete, without ever suggesting one somebody was halfway through.**

Broomarr reads your Sonarr library and your Tautulli watch history and answers one question per show: has the person who was watching this actually finished it, and is there genuinely nothing left for them to watch? It prints a shortlist. You delete through Sonarr yourself.

## What it checks

Broomarr makes **one decision** - safe to delete, or not - and it applies **six conditions, all of which must hold**. It is not a rule engine and there is nothing to configure beyond who the watcher is and how long the quiet period lasts. That is deliberate: a rule you can express is a rule you can express wrongly.

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

## The two ideas that make it different

**An unknown value blocks.** Rule engines usually skip a condition they cannot evaluate, which switches a safety check off while the configuration still reads as correct. Here, anything that cannot be established is a reason not to delete. No watch history, an unreachable Sonarr, a missing timestamp - all block.

**No decision is ever made from a count.** Condition 2 is not "watched 10, and 10 are on disk". It is a comparison of which episodes, one by one. Counts hide things: Sonarr's own `episodeCount` and `episodeFileCount` both exclude unmonitored episodes, so they can agree while an entire season is missing. Two numbers agreeing is not corroboration when both carry the same hidden filter.

Together these are why Broomarr asks Sonarr rather than the media server. Plex, Jellyfin and Emby can only tell you about episodes that were downloaded, so a half-fetched series reports as fully watched the moment somebody finishes a later season. Sonarr knows the real episode list. `docs/DESIGN.md` makes the full argument, including a fair account of why [Maintainerr](https://github.com/jorenn92/Maintainerr) was used first and then replaced.

## Broomarr never deletes anything

No `--delete` flag, no write call to any API, no filesystem access. This is not a feature waiting to be added - it is the property everything else rests on. A tool that can delete has to be right on every run, including the ones nobody watched. A tool that prints a list has to be right only while somebody is reading it, with the reasoning in front of them.

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
| `watcher` | the Tautulli friendly name whose viewing decides, matched case-insensitively as a substring |
| `quiet_days` | how long a show must be left alone, default 14 |

## Running it

Run this first. It confirms both services answer and that your `watcher` matches a real Tautulli name, without scanning anything:

```
python src/broomarr.py --check
```

Then:

```
python src/broomarr.py --all              scan the whole library
python src/broomarr.py "Some Show"        explain one show in full
```

On Windows, `scripts\run.bat` prompts for the mode and keeps the window open.

The single-show form prints what Sonarr holds, which episodes were never downloaded, who watched how many and when, and every reason the show is or is not a candidate. Reach for it whenever you disagree with the scan - it is the same six conditions, shown working.

## Tests

```
python -m pytest tests -q
```

The suite is mostly deletions that must not happen, including regression fixtures for the two failures that shaped the design: a series whose counts agree while a whole season is missing, and one where the watcher's episode count matches the number on disk but they are not the same episodes.

## Scope

TV only. Movies are a simpler version of the same join and are planned next. Broomarr holds no state, reads from both services and writes to neither, so it sits alongside whatever else manages your library.

**Status:** Active development. TV support is complete; movie support is next.

## Licence

MIT.
