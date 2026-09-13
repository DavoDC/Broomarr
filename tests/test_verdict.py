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


def history_row(show="A Show", user="Watcher", season=2, ep=1,
                watched=1.0, stopped=None):
    """One Tautulli get_history row, in the shape watch_index() consumes."""
    return {
        "grandparent_title": show,
        "friendly_name": user,
        "parent_media_index": season,
        "media_index": ep,
        "watched_status": watched,
        "stopped": LONG_AGO if stopped is None else stopped,
    }


def tautulli_library(rows):
    """A Library wired to fixed Tautulli history instead of a live Tautulli.

    get_history is paginated in the real API, so response.data is itself
    {"data": [rows], ...} - one nesting level deeper than other Tautulli
    endpoints. watch_index() unwraps that inner "data" key.
    """
    return broomarr.Library(
        CONFIG,
        fetch=lambda url, headers=None: {"response": {"data": {"data": rows}}},
        now=NOW)


def checked_library(series_list, history_rows, watcher="Watcher"):
    """A Library wired to both a fixed Sonarr series list and fixed Tautulli
    history, dispatching on which service's base URL the call was for - for
    exercising --check and the scan() watcher-mismatch warning, neither of
    which touches the per-episode endpoint.
    """
    cfg = dict(CONFIG, watcher=watcher)

    def fetch(url, headers=None):
        if url.startswith(cfg["sonarr_url"]):
            return series_list
        return {"response": {"data": {"data": history_rows}}}

    return broomarr.Library(cfg, fetch=fetch, now=NOW)


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
    """Rewritten against identifiers: the count comparison this asserted on
    ("watched 3 of the 6") was deleted along with the count-based verdict
    path. The behaviour it protected still holds - partial coverage still
    blocks - it is now the identity join that catches it.
    """
    lib = library([episode(1, n) for n in range(1, 7)])
    safe, reasons = lib.verdict(series(), watchers(3, season=1))
    assert not safe
    assert any("S01E04" in r and "S01E05" in r and "S01E06" in r
               for r in reasons)


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


def test_watched_episodes_dont_match_on_disk_episodes_blocks_even_though_counts_agree():
    """The regression case for the count-vs-identity defect.

    Counts agree at 10 vs 10 - the watcher has 10 distinct episodes, and
    10 episodes are on disk - so a count comparison passes this outright.
    The watcher's 10 are S01E01-E10; the 10 on disk are S01E01-E07 plus
    S02E01-E03. Season 2 was never watched. `missing` and `upcoming` are
    both empty (nothing aired-without-file, nothing unaired), so only an
    identity join catches this - a count cannot.
    """
    episodes = ([episode(1, n) for n in range(1, 8)]
                + [episode(2, n) for n in range(1, 4)])
    lib = library(episodes)
    watched = {"Watcher": {"eps": {(1, n) for n in range(1, 11)},
                           "last": LONG_AGO}}
    safe, reasons = lib.verdict(series(on_disk=10, aired_count=10), watched)
    assert not safe
    assert any("S02E01" in r and "S02E02" in r and "S02E03" in r
               for r in reasons)


def test_identical_identities_with_equal_counts_is_safe():
    """The identity check is not just a stricter check that blocks everything.

    Same ten-on-disk shape as the regression case above, but this time the
    watcher's identities actually match what is on disk. Must still pass -
    a fix that always blocks is not a fix.
    """
    episodes = ([episode(1, n) for n in range(1, 8)]
                + [episode(2, n) for n in range(1, 4)])
    lib = library(episodes)
    watched = {"Watcher": {"eps": ({(1, n) for n in range(1, 8)}
                                   | {(2, n) for n in range(1, 4)}),
                           "last": LONG_AGO}}
    safe, reasons = lib.verdict(series(), watched)
    assert safe, reasons


def test_episode_in_unstarted_season_blocks():
    """An episode on disk in a season the watcher never started must block,
    independent of counts - here the watcher is one episode short of the
    on-disk total anyway, but the point is the identity, not the count.
    """
    episodes = [episode(1, n) for n in range(1, 7)] + [episode(2, 1)]
    lib = library(episodes)
    safe, reasons = lib.verdict(series(), watchers(6, season=1))
    assert not safe
    assert any("S02E01" in r for r in reasons)


def test_tautulli_string_season_episode_still_joins():
    """Tautulli returns season/episode as strings in some API versions.

    watch_index() must coerce both sides to int so the identifier sets in
    verdict() actually intersect. A silent type mismatch here would make
    every on-disk episode read as unwatched - safe, but useless, since it
    would block every show forever without anyone noticing why.
    """
    rows = [history_row(season=str(2), ep=str(n)) for n in range(1, 7)]
    lib = tautulli_library(rows)
    index = lib.watch_index()
    assert index["a show"]["Watcher"]["eps"] == {(2, n) for n in range(1, 7)}


def test_unusable_season_or_episode_value_is_not_counted_as_watched():
    """A history row whose season or episode cannot be coerced to an int
    must not silently count as a watched episode - unknown blocks, it does
    not pass by omission.
    """
    rows = [history_row(season=2, ep=1),
           history_row(season=None, ep=2),
           history_row(season=2, ep="not-a-number")]
    lib = tautulli_library(rows)
    index = lib.watch_index()
    assert index["a show"]["Watcher"]["eps"] == {(2, 1)}


def test_cheap_pass_never_blocks_what_the_strict_pass_would_examine():
    """The prefilter invariant this tool depends on.

    Take a case the strict pass blocks purely on the episode-list identity
    check (not on a count - counts no longer drive any verdict path): the
    on-disk episodes do not match what the watcher saw. The strict pass
    must block it. The cheap pass, which does not look at episode data at
    all, must let the same case through unconditionally - the prefilter
    can never be stricter than the check it is filtering for.
    """
    episodes = [episode(1, n) for n in range(1, 7)] + [episode(2, 1)]
    watched = watchers(6, season=1)

    strict_lib = library(episodes)
    strict_safe, strict_reasons = strict_lib.verdict(series(), watched)
    assert not strict_safe
    assert any("S02E01" in r for r in strict_reasons)

    def explode(url, headers=None):
        raise AssertionError("deep=False must not hit the episode endpoint")

    cheap_lib = broomarr.Library(CONFIG, fetch=explode, now=NOW)
    cheap_safe, _ = cheap_lib.verdict(series(), watched, deep=False)
    assert cheap_safe


def test_config_requires_the_keys_it_needs(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"sonarr_url": "http://sonarr"}', encoding="utf-8")
    with pytest.raises(SystemExit):
        broomarr.load_config(str(path))


def test_missing_config_is_a_clear_error(tmp_path):
    with pytest.raises(SystemExit):
        broomarr.load_config(str(tmp_path / "nope.json"))


def test_matches_watcher_is_case_insensitive_substring():
    """The rule reused everywhere a Tautulli friendly name is checked
    against the configured watcher: case-insensitive substring."""
    lib = library([])
    assert lib.matches_watcher("Watcher")
    assert lib.matches_watcher("SuperWatcherFan")
    assert lib.matches_watcher("watcher")
    assert not lib.matches_watcher("Someone Else")


def test_verdict_uses_the_same_matching_rule_as_matches_watcher():
    """verdict() must not reimplement the matching rule - it has to call
    matches_watcher() so a fix to one rule fixes both call sites. Proven
    behaviourally: a name that only matches via case-insensitive substring
    (not equality) still gets picked up as the watcher inside verdict().
    """
    lib = library([episode(1, n) for n in range(1, 7)])
    users = {"SuperWatcherFan": {"eps": {(1, n) for n in range(1, 7)},
                                 "last": LONG_AGO}}
    safe, reasons = lib.verdict(series(), users)
    assert safe, reasons


def test_empty_episode_list_blocks_rather_than_passes():
    """Sonarr returning a literal [] must not read as "nothing missing."

    Before the fix, an empty episode list made all three verdict checks
    (missing, upcoming, unwatched) no-op false, and the show passed on the
    strength of a response that established nothing. This test fails on the
    current code - confirm that before fixing.
    """
    lib = library([])
    safe, reasons = lib.verdict(series(), watchers(6, season=1))
    assert not safe
    assert any("episode" in r.lower() for r in reasons)


def test_null_episode_response_blocks():
    lib = library(None)
    safe, reasons = lib.verdict(series(), watchers(6, season=1))
    assert not safe
    assert any("episode" in r.lower() for r in reasons)


def test_non_list_episode_response_blocks():
    lib = library({"error": "not found"})
    safe, reasons = lib.verdict(series(), watchers(6, season=1))
    assert not safe
    assert any("episode" in r.lower() for r in reasons)


def test_all_episodes_unaired_blocks_on_empty_on_disk():
    """A real list whose episodes all lie in the future - on_disk_eps is
    legitimately empty, not unreadable. Must still block, on the upcoming
    reason and on the empty-on-disk reason both."""
    episodes = [episode(1, n, has_file=False, aired=False) for n in range(1, 7)]
    lib = library(episodes)
    safe, reasons = lib.verdict(series(), watchers(6, season=1))
    assert not safe
    assert any("not yet aired" in r for r in reasons)
    assert any("nothing to verify against" in r for r in reasons)


def test_check_passes_when_watcher_matches_a_friendly_name(capsys):
    lib = checked_library([series()], [history_row(user="Watcher")])
    ok = broomarr.check(lib)
    assert ok
    out = capsys.readouterr().out
    assert "[FAIL]" not in out


def test_check_fails_when_watcher_matches_no_friendly_name(capsys):
    lib = checked_library([series()], [history_row(user="Someone Else")])
    ok = broomarr.check(lib)
    assert not ok
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "Someone Else" in out


def test_check_does_not_call_the_episode_endpoint():
    """--check has to be fast and read-only: no per-episode calls."""
    def explode(url, headers=None):
        if "/episode" in url:
            raise AssertionError("--check must not hit the episode endpoint")
        if url.startswith(CONFIG["sonarr_url"]):
            return [series()]
        return {"response": {"data": {"data": [history_row(user="Watcher")]}}}

    lib = broomarr.Library(CONFIG, fetch=explode, now=NOW)
    broomarr.check(lib)


def test_scan_warns_when_watcher_matches_no_friendly_name(capsys):
    """The trap this guards: a wrong `watcher` value is otherwise
    indistinguishable from a genuinely clean library - every show blocks
    with no hint that the config, not the library, is the problem."""
    lib = checked_library([series()], [history_row(user="Someone Else")])
    broomarr.scan(lib)
    out = capsys.readouterr().out
    assert "[WARNING]" in out
    assert "Someone Else" in out


def test_scan_does_not_warn_when_watcher_matches_a_friendly_name(capsys):
    lib = checked_library(
        [series()], [history_row(user="Watcher", stopped=YESTERDAY)])
    broomarr.scan(lib)
    out = capsys.readouterr().out
    assert "[WARNING]" not in out
