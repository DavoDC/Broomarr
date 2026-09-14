"""The movie-side decision logic, mirroring test_verdict.py's style and
its bias: every test here is a deletion that must not happen, except the
one that establishes a genuinely finished film still comes through.

The most important test on this side is test_partial_view_blocks - a
partial view is the entire watch signal for a film, where on the TV side
it is harmless because the set difference still names the other episodes.
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
    "radarr_url": "http://radarr",
    "radarr_api_key": "x",
    "watcher": "Watcher",
    "quiet_days": 14,
}


def movie(id=1, title="A Film", year=2020, status="released",
         has_file=True, size_bytes=5_000_000_000):
    return {
        "id": id,
        "title": title,
        "year": year,
        "status": status,
        "hasFile": has_file,
        "sizeOnDisk": size_bytes,
    }


def movie_history_row(title="A Film", year=2020, user="Watcher",
                      watched=1.0, stopped=None):
    """One Tautulli get_history row for media_type=movie."""
    return {
        "title": title,
        "year": year,
        "friendly_name": user,
        "watched_status": watched,
        "stopped": LONG_AGO if stopped is None else stopped,
    }


def movie_library(movies_list, history_rows):
    """A MovieLibrary wired to a fixed Radarr movie list and fixed
    Tautulli history, dispatching on which service's base URL the call
    was for - mirrors test_verdict.py's checked_library()."""
    def fetch(url, headers=None):
        if url.startswith(CONFIG["radarr_url"]):
            return movies_list
        return {"response": {"data": {"data": history_rows}}}

    return broomarr.MovieLibrary(CONFIG, fetch=fetch, now=NOW)


def verdict_of(lib, target):
    """Run the same join movie_scan() would: look the target movie's
    watch history up in the bulk index by its (title, year) key."""
    key = broomarr._movie_key(target)
    users = lib.movie_watch_index().get(key, {}) if key else {}
    return lib.verdict(target, users)


def test_finished_movie_is_safe():
    lib = movie_library([movie()], [movie_history_row(stopped=LONG_AGO)])
    safe, reasons = verdict_of(lib, movie())
    assert safe, reasons


def test_movie_with_no_file_blocks():
    lib = movie_library([movie(has_file=False)],
                        [movie_history_row(stopped=LONG_AGO)])
    safe, reasons = verdict_of(lib, movie(has_file=False))
    assert not safe
    assert any("file" in r.lower() for r in reasons)


def test_unreleased_movie_blocks():
    lib = movie_library([movie(status="announced")],
                        [movie_history_row(stopped=LONG_AGO)])
    safe, reasons = verdict_of(lib, movie(status="announced"))
    assert not safe
    assert any("not yet released" in r for r in reasons)


def test_in_cinemas_movie_blocks():
    """inCinemas is not released - a digital release is still coming."""
    lib = movie_library([movie(status="inCinemas")],
                        [movie_history_row(stopped=LONG_AGO)])
    safe, reasons = verdict_of(lib, movie(status="inCinemas"))
    assert not safe
    assert any("not yet released" in r for r in reasons)


def test_unrecognised_status_blocks():
    lib = movie_library([movie(status="somethingNew")],
                        [movie_history_row(stopped=LONG_AGO)])
    safe, reasons = verdict_of(lib, movie(status="somethingNew"))
    assert not safe
    assert any("unrecognised" in r.lower() for r in reasons)


def test_partial_view_blocks():
    """The most important test on the movie side. A partial view - here
    watched_status 0.3 - is the entire watch signal for a film; there is
    no per-episode set difference to fall back on. Must block."""
    lib = movie_library([movie()], [movie_history_row(watched=0.3)])
    safe, reasons = verdict_of(lib, movie())
    assert not safe
    assert any("never finished" in r for r in reasons)


def test_no_history_blocks():
    lib = movie_library([movie()], [])
    safe, reasons = verdict_of(lib, movie())
    assert not safe
    assert any("no watch history" in r for r in reasons)


def test_a_different_user_watching_it_is_not_enough():
    lib = movie_library([movie()],
                        [movie_history_row(user="Someone Else")])
    safe, reasons = verdict_of(lib, movie())
    assert not safe
    assert any("no watch history for this movie" in r for r in reasons)


def test_recent_view_blocks_rather_than_qualifies():
    lib = movie_library([movie()], [movie_history_row(stopped=YESTERDAY)])
    safe, reasons = verdict_of(lib, movie())
    assert not safe
    assert any("quiet period" in r for r in reasons)


def test_missing_last_view_timestamp_blocks():
    lib = movie_library([movie()], [movie_history_row(stopped=0)])
    safe, reasons = verdict_of(lib, movie())
    assert not safe
    assert any("quiet period" in r for r in reasons)


def test_title_matches_but_year_does_not_is_not_a_match():
    """The join is two-part: title alone is not enough."""
    lib = movie_library([movie(year=2020)],
                        [movie_history_row(year=2019, stopped=LONG_AGO)])
    safe, reasons = verdict_of(lib, movie(year=2020))
    assert not safe
    assert any("no watch history" in r for r in reasons)


def test_uncoercible_year_row_is_not_counted_as_watched():
    lib = movie_library([movie()], [movie_history_row(year="not-a-number")])
    index = lib.movie_watch_index()
    assert ("a film", 2020) not in index


def test_duplicate_title_and_year_in_radarr_blocks_both():
    """Two Radarr entries sharing (title, year) can't be told apart -
    both must block, not just the second one seen."""
    dup_a = movie(id=1)
    dup_b = movie(id=2)
    lib = movie_library([dup_a, dup_b], [movie_history_row(stopped=LONG_AGO)])
    safe_a, reasons_a = verdict_of(lib, dup_a)
    safe_b, reasons_b = verdict_of(lib, dup_b)
    assert not safe_a
    assert not safe_b
    assert any("share this title and year" in r for r in reasons_a)
    assert any("share this title and year" in r for r in reasons_b)


def test_unreachable_radarr_blocks_rather_than_skips():
    def explode(url, headers=None):
        if url.startswith(CONFIG["radarr_url"]):
            raise OSError("connection refused")
        return {"response": {"data": {"data": [movie_history_row(stopped=LONG_AGO)]}}}

    lib = broomarr.MovieLibrary(CONFIG, fetch=explode, now=NOW)
    users = {"Watcher": {"watched": True, "last": LONG_AGO}}
    safe, reasons = lib.verdict(movie(), users)
    assert not safe
    assert any("radarr" in r.lower() for r in reasons)


def test_movie_facts_returns_none_not_empty_for_a_missing_id():
    lib = movie_library([movie(id=1)], [])
    assert lib.movie_facts(999) is None
    facts = lib.movie_facts(1)
    assert facts.on_disk is True
    assert facts.released is True


def test_verdict_trusts_the_live_radarr_record_not_a_stale_caller_copy():
    """verdict() must read hasFile/status through movie_facts() - the
    same lookup against Radarr's current bulk list that movie_facts()
    already does - rather than off whatever fields happen to be on the
    movie dict the caller passed in. Here the caller's copy still says
    hasFile=True, but Radarr's live list (queried by id) now says
    hasFile=False: the live record must win, or a scan holding a stale
    in-memory copy could call a since-deleted-on-disk file safe.
    """
    live_movie = movie(id=1, has_file=False)
    stale_caller_copy = movie(id=1, has_file=True)
    lib = movie_library([live_movie], [movie_history_row(stopped=LONG_AGO)])
    safe, reasons = lib.verdict(stale_caller_copy, {"Watcher": {
        "watched": True, "last": LONG_AGO}})
    assert not safe
    assert any("file" in r.lower() for r in reasons)


def test_verdict_blocks_when_the_movie_is_no_longer_in_radarrs_list():
    """Unknown blocks: if the id cannot be found in Radarr's current
    bulk list at all, that is not "assume the caller's copy is still
    good" - it is a fact Broomarr cannot establish, so it blocks.
    """
    lib = movie_library([movie(id=2)], [movie_history_row(stopped=LONG_AGO)])
    safe, reasons = lib.verdict(movie(id=1), {"Watcher": {
        "watched": True, "last": LONG_AGO}})
    assert not safe
    assert any("could not find" in r.lower() for r in reasons)


def test_movie_config_requires_both_radarr_keys_together(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"sonarr_url": "http://sonarr", "sonarr_api_key": "x", '
        '"tautulli_url": "http://tautulli", "tautulli_api_key": "x", '
        '"watcher": "Watcher", "radarr_url": "http://radarr"}',
        encoding="utf-8")
    with pytest.raises(SystemExit):
        broomarr.load_config(str(path))
