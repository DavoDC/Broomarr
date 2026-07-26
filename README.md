# Broomarr

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/G2G31WKOCN)

**Reclaim disk space from finished TV shows without ever deleting one somebody was halfway through.**

Broomarr looks at your Sonarr library and your Tautulli watch history and answers one question per show: has the person who was watching this actually finished it, and is there genuinely nothing left for them to watch? Only if every part of that is provably true does the show appear on the list.

```
python src/broomarr.py --all
```

```
Scanning library. Sonarr for what exists, Tautulli for who watched it.
  187 series in Sonarr, 164 with watch history

========================================================================
SAFE TO DELETE
========================================================================
  A Finished Drama                                 27.0 GB
  An Old Sitcom                                     8.1 GB

  2 show(s), 35.1 GB

========================================================================
LOOKED FINISHED, BLOCKED ON A CLOSER LOOK
========================================================================
  These are the ones a count-based rule would get wrong.

  A Show That Looks Complete
      - 8 aired episode(s) never downloaded: S01E01, S01E02, S01E03 ...
```

That second section is the reason this exists.

## Why the obvious approach quietly deletes the wrong thing

Every automated library cleaner asks the media server whether a show has been fully watched. The media server can only answer for episodes that were downloaded. A series where season 1 never arrived reports as fully watched the moment somebody finishes season 2, and its own episode counts agree, because **`episodeCount` in Sonarr excludes unmonitored episodes and so does `episodeFileCount`.** Two numbers agreeing is not confirmation when both share the same hidden filter.

Broomarr never uses a count. It enumerates the real episode list from Sonarr, checks each episode individually, and joins that against the specific episodes Tautulli saw a specific person watch. `docs/DESIGN.md` has the full argument, including a fair account of why [Maintainerr](https://github.com/jorenn92/Maintainerr) was used first and then replaced - it skips rules it cannot evaluate, and its watched-every-episode check is answered by Plex.

## The safety model

**An unknown value blocks.** This is the single design rule everything else follows from. Rule engines typically skip a condition they cannot evaluate, which silently switches a safety check off while the configuration still reads as correct. Here, anything that cannot be established is a reason not to delete: no watch history, an unreachable Sonarr, a missing timestamp, all block.

**Broomarr never deletes anything, and never will.** No `--delete` flag, no API write, no filesystem access. It produces a shortlist; you delete through Sonarr yourself. A tool that cannot delete cannot delete the wrong thing, and that property is worth more than the keystrokes it costs.

A show reaches the list only when all of these hold:

| Check | Blocks when |
|---|---|
| The named watcher has history for the show | they never started it |
| They watched every episode on disk | any gap at all |
| Every aired episode is on disk | a season was never fetched |
| No episodes are pending broadcast | more are coming |
| The series has finished airing | Sonarr still marks it continuing |
| Nobody has touched it for the quiet period | watched recently |

Recency blocks. It is worth stating plainly because the failure that prompted this tool came from a rule where "watched in the last 14 days" was OR-ed rather than AND-ed, making active viewing a deletion trigger.

## Setup

Needs Python 3.8 or newer and nothing else - no dependencies, standard library only.

```
git clone https://github.com/<you>/Broomarr.git
cd Broomarr
cp config/config.example.json config/config.json
```

Fill in `config/config.json` (gitignored, so your keys stay local):

| Field | Where to find it |
|---|---|
| `sonarr_url`, `sonarr_api_key` | Sonarr, Settings - General - API Key |
| `tautulli_url`, `tautulli_api_key` | Tautulli, Settings - Web Interface - API Key |
| `watcher` | the Tautulli friendly name whose viewing decides, matched case-insensitively as a substring |
| `quiet_days` | how long a show must be left alone, default 14 |

Then:

```
python src/broomarr.py --all              scan the whole library
python src/broomarr.py "Some Show"        explain one show's verdict in full
```

The single-show form prints what Sonarr holds, which episodes were never downloaded, who watched how many, and every reason the show is or is not a candidate. Use it when you disagree with the scan.

## Tests

```
python -m pytest tests -q
```

The suite is mostly deletions that must not happen, including a regression fixture for the missing-season case above: counts agree, every count-based check passes, and Broomarr blocks.

## Scope

TV only for now. Movies are a simpler version of the same join and are the next thing planned. Broomarr talks to Sonarr and Tautulli directly, so it works alongside whatever else manages your library, and reads from both - it holds no state of its own.

## Licence

MIT.
