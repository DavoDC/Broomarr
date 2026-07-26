"""The decision logic, exercised against the cases that matter.

Every test here is a deletion that must not happen, except the two that
establish a genuinely finished show still comes through. The bias is
deliberate: a missed deletion costs disk space, a wrong one is permanent.
"""

import datetime

import pytest

import broomarr


NOW = datetime.datetime(2026, 7, 26, tzinfo=datetime.timezone.utc)
LONG_AGO = (NOW - datetime.timedelta(days=200)).timestamp()
YESTERDAY = (NOW - datetime.timedelta(days=1)).timestamp()

CONFIG = {
    "sonarr_url": "http://sonarr",
    "sonarr_api_key": "x",
    "tautulli_url": "http://tautulli",
    "tautulli_api_key": "x",
    "watcher": "Watcher",
    "quiet_days": 14,
}


def episode(season, number, has_file=True, monitored=True, aired=True):
    when = NOW - datetime.timedelta(days=30 if aired else -30)
    return {
        "seasonNumber": season,
        "episodeNumber": number,
        "hasFile": has_file,
        "monitored": monitored,
        "airDateUtc": when.isoformat().replace("+00:00", "Z"),
    }


def series(title="A Show", ended=True, on_disk=6, aired_count=6):
    return {
        "id": 1,
        "title": title,
        "tvdbId": 1,
        "status": "ended" if ended else "continuing",
        "ended": ended,
        "statistics": {
            "episodeFileCount": on_disk,
            "episodeCount": aired_count,
            "sizeOnDisk": 6_000_000_000,
        },
    }


def watchers(count, last=LONG_AGO, name="Watcher", season=2):
    return {name: {"eps": {(season, n) for n in range(1, count + 1)},
                   "last": last}}


def library(episodes):
    """A Library wired to a fixed episode list instead of a live Sonarr."""
    return broomarr.Library(CONFIG, fetch=lambda url, headers=None: episodes,
                            now=NOW)


def test_finished_show_is_safe():
    lib = library([episode(1, n) for n in range(1, 7)])
    safe, reasons = lib.verdict(series(), watchers(6, season=1))
    assert safe, reasons


def test_missing_first_season_blocks_even_though_counts_agree():
    """The case this tool exists for.

    Sonarr reports 6 episodes aired and 6 on disk, so by arithmetic the
    series is complete, and the watcher has 6 distinct episodes. Every
    count-based check passes. In reality season 1 was never downloaded and
    the watcher only ever saw season 2 - deleting here destroys a series
    somebody is midway through.
    """
    episodes = ([episode(1, n, has_file=False, monitored=False) for n in range(1, 9)]
                + [episode(2, n) for n in range(1, 7)])
    lib = library(episodes)
    safe, reasons = lib.verdict(series(), watchers(6, season=2))
    assert not safe
    assert any("never downloaded" in r for r in reasons)


def test_unmonitored_missing_episodes_still_count_as_missing():
    """An unmonitored episode is one Sonarr will never fetch.

    It is still an episode nobody can watch. Filtering by `monitored` here
    reproduces exactly the hidden filter that makes episodeCount unsafe.
    """
    episodes = [episode(1, n) for n in range(1, 6)]
    episodes.append(episode(1, 6, has_file=False, monitored=False))
    lib = library(episodes)
    safe, reasons = lib.verdict(series(), watchers(5, season=1))
    assert not safe
    assert any("never downloaded" in r for r in reasons)


def test_unaired_episodes_block():
    episodes = [episode(1, n) for n in range(1, 7)]
    episodes.append(episode(2, 1, has_file=False, aired=False))
    lib = library(episodes)
    safe, reasons = lib.verdict(series(), watchers(6, season=1))
    assert not safe
    assert any("not yet aired" in r for r in reasons)


def test_still_airing_blocks():
    lib = library([episode(1, n) for n in range(1, 7)])
    safe, reasons = lib.verdict(series(ended=False), watchers(6, season=1))
    assert not safe
    assert any("still airing" in r for r in reasons)


def test_recent_view_blocks_rather_than_qualifies():
    """Recency is a reason to keep, never a reason to delete.

    An OR between "watched everything" and "watched recently" made active
    viewing a deletion trigger. It is an AND, and recency blocks.
    """
    lib = library([episode(1, n) for n in range(1, 7)])
    safe, reasons = lib.verdict(series(), watchers(6, last=YESTERDAY, season=1))
    assert not safe
    assert any("quiet period" in r for r in reasons)


def test_partial_watch_blocks():
    lib = library([episode(1, n) for n in range(1, 7)])
    safe, reasons = lib.verdict(series(), watchers(3, season=1))
    assert not safe
    assert any("watched 3 of the 6" in r for r in reasons)


def test_no_history_at_all_blocks():
    lib = library([episode(1, n) for n in range(1, 7)])
    safe, reasons = lib.verdict(series(), {})
    assert not safe
    assert any("no watch history" in r for r in reasons)


def test_a_different_user_finishing_it_is_not_enough():
    lib = library([episode(1, n) for n in range(1, 7)])
    safe, reasons = lib.verdict(series(), watchers(6, name="Someone Else"))
    assert not safe
    assert any("no watch history for this show" in r for r in reasons)


def test_missing_last_view_timestamp_blocks():
    lib = library([episode(1, n) for n in range(1, 7)])
    safe, reasons = lib.verdict(series(), watchers(6, last=0, season=1))
    assert not safe
    assert any("quiet period" in r for r in reasons)


def test_unreachable_sonarr_blocks_rather_than_skips():
    """An unresolvable value must fail, not be skipped.

    A rule engine that skips a check it cannot evaluate silently turns the
    safety condition off while the configuration still reads as correct.
    """
    def explode(url, headers=None):
        raise OSError("connection refused")

    lib = broomarr.Library(CONFIG, fetch=explode, now=NOW)
    safe, reasons = lib.verdict(series(), watchers(6, season=1))
    assert not safe
    assert any("could not read episode list" in r for r in reasons)


def test_specials_are_ignored():
    """Season 0 holds TVDB extras that were never meant to be downloaded.

    Counting them makes every complete show look permanently incomplete,
    which trains the operator to ignore the warning.
    """
    episodes = [episode(1, n) for n in range(1, 7)]
    episodes += [episode(0, n, has_file=False) for n in range(1, 31)]
    lib = library(episodes)
    safe, reasons = lib.verdict(series(), watchers(6, season=1))
    assert safe, reasons


def test_cheap_pass_does_not_call_sonarr():
    """The prefilter is permissive and cheap; the strict check is the gate."""
    def explode(url, headers=None):
        raise AssertionError("deep=False must not hit the episode endpoint")

    lib = broomarr.Library(CONFIG, fetch=explode, now=NOW)
    safe, _ = lib.verdict(series(), watchers(6, season=1), deep=False)
    assert safe


def test_config_requires_the_keys_it_needs(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"sonarr_url": "http://sonarr"}', encoding="utf-8")
    with pytest.raises(SystemExit):
        broomarr.load_config(str(path))


def test_missing_config_is_a_clear_error(tmp_path):
    with pytest.raises(SystemExit):
        broomarr.load_config(str(tmp_path / "nope.json"))
