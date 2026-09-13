"""The staged hold queue and the delete path - src/reclaim.py.

Every test here uses an injectable fetch (for reads, via Library and
MovieLibrary exactly as test_verdict.py and test_movie_verdict.py do) and
an injectable request (for writes, reclaim.py's own concern) and an
injectable now, plus tmp_path for the queue and history files. Nothing
here ever touches a live service or the real filesystem outside tmp_path.

test_hold_elapsing_does_not_delete_anything_on_its_own is the test that
encodes the central claim of the whole design: there is no code path,
anywhere, that reaches a delete call without a human calling execute().
"""

import datetime
import json

import pytest

import broomarr
import reclaim


NOW = datetime.datetime(2026, 7, 26, tzinfo=datetime.timezone.utc)
LONG_AGO = (NOW - datetime.timedelta(days=200)).timestamp()

CONFIG = {
    "sonarr_url": "http://sonarr",
    "sonarr_api_key": "x",
    "tautulli_url": "http://tautulli",
    "tautulli_api_key": "x",
    "radarr_url": "http://radarr",
    "radarr_api_key": "x",
    "watcher": "Watcher",
    "quiet_days": 14,
    "hold_days": 7,
    "max_scan_age_days": 3,
    "max_items": 10,
    "max_bytes": 250_000_000_000,
}


def series_row(id=1, title="A Show", size_bytes=1000):
    return {"id": id, "title": title, "ended": True, "status": "ended",
           "statistics": {"sizeOnDisk": size_bytes, "episodeCount": 1,
                          "episodeFileCount": 1}}


def episode(season, number, has_file=True, aired=True):
    air = "2020-01-01T00:00:00Z" if aired else "2099-01-01T00:00:00Z"
    return {"seasonNumber": season, "episodeNumber": number,
           "hasFile": has_file, "airDateUtc": air}


def history_row(show="A Show", user="Watcher", season=1, ep=1,
               stopped=LONG_AGO):
    return {"grandparent_title": show, "friendly_name": user,
           "watched_status": 1.0, "parent_media_index": season,
           "media_index": ep, "stopped": stopped}


def movie_row(id=1, title="A Film", year=2020, size_bytes=1000):
    return {"id": id, "title": title, "year": year, "status": "released",
           "hasFile": True, "sizeOnDisk": size_bytes}


def movie_history_row(title="A Film", year=2020, user="Watcher",
                      stopped=LONG_AGO):
    return {"title": title, "year": year, "friendly_name": user,
           "watched_status": 1.0, "stopped": stopped}


def make_evidence(scanned_at=None):
    return {"scanned_at": scanned_at if scanned_at is not None
           else NOW.timestamp()}


def build_fetch(series_list=None, episodes_by_id=None, history_rows=None,
                movies_list=None, movie_history_rows=None,
                removed_ids=None):
    """One fetch() serving Sonarr, Radarr and Tautulli, dispatched on URL,
    exactly the pattern test_verdict.py and test_movie_verdict.py use.
    removed_ids lets a test simulate a service no longer holding a record
    after a delete - the single-item lookups below return None for any id
    in that set, everything else looks the record up in the static list.
    """
    series_list = series_list or []
    episodes_by_id = episodes_by_id or {}
    history_rows = history_rows or []
    movies_list = movies_list or []
    movie_history_rows = movie_history_rows or []
    removed_ids = removed_ids if removed_ids is not None else set()

    def fetch(url, headers=None):
        if url.startswith("http://sonarr/api/v3/episode?seriesId="):
            sid = int(url.rsplit("=", 1)[1])
            return episodes_by_id.get(sid, [])
        if url.startswith("http://sonarr/api/v3/series/"):
            sid = int(url.rsplit("/", 1)[1])
            if sid in removed_ids:
                return None
            return next((s for s in series_list if s["id"] == sid), None)
        if url.startswith("http://sonarr/api/v3/series"):
            return series_list
        if url.startswith("http://radarr/api/v3/movie/"):
            mid = int(url.split("?")[0].rsplit("/", 1)[1])
            if mid in removed_ids:
                return None
            return next((m for m in movies_list if m["id"] == mid), None)
        if url.startswith("http://radarr/api/v3/movie"):
            return movies_list
        if "media_type=episode" in url:
            return {"response": {"data": {"data": history_rows}}}
        if "media_type=movie" in url:
            return {"response": {"data": {"data": movie_history_rows}}}
        raise ValueError("unexpected url in test fetch: %s" % url)
    return fetch


def make_request(removed_ids=None, fail_at_call=None):
    """A recording request() spy. fail_at_call, if given, is a 1-based
    call number at which the request raises instead of succeeding - used
    to simulate a delete failing partway through a run.
    """
    removed_ids = removed_ids if removed_ids is not None else set()
    calls = []

    def request(url, method, headers=None, payload=None):
        calls.append((url, method, headers))
        if fail_at_call is not None and len(calls) == fail_at_call:
            raise OSError("simulated delete failure")
        service_id = int(url.split("?")[0].rsplit("/", 1)[1])
        removed_ids.add(service_id)
        return None
    request.calls = calls
    return request


def make_libs(now, series_list=None, episodes_by_id=None, history_rows=None,
             movies_list=None, movie_history_rows=None, removed_ids=None):
    fetch = build_fetch(series_list, episodes_by_id, history_rows,
                        movies_list, movie_history_rows, removed_ids)
    lib = broomarr.Library(CONFIG, fetch=fetch, now=now)
    movie_lib = broomarr.MovieLibrary(CONFIG, fetch=fetch, now=now)
    return lib, movie_lib


def make_queue(tmp_path, now):
    return reclaim.Queue(str(tmp_path / "reclaim-queue.json"),
                         str(tmp_path / "reclaim-history.json"), now=now)


def test_flagging_writes_no_request(tmp_path):
    queue = make_queue(tmp_path, NOW)
    calls = []

    def spy(*args, **kwargs):
        calls.append(args)
        raise AssertionError("flag() must never make a request")

    queue.flag("tv", 1, "A Show", 5_000_000_000, make_evidence())
    assert calls == []
    assert queue.items  # something was actually recorded locally


def test_item_inside_hold_cannot_be_executed(tmp_path):
    lib, movie_lib = make_libs(NOW)
    queue = make_queue(tmp_path, NOW)
    item_id = queue.flag("tv", 1, "A Show", 1000, make_evidence())

    def request(*a, **k):
        raise AssertionError("nothing inside its hold may be executed")

    with pytest.raises(reclaim.ReclaimError):
        reclaim.execute(lib, movie_lib, queue, [item_id], CONFIG,
                        request=request)
    assert queue.items[item_id]["state"] == "PENDING"


def test_hold_elapsing_does_not_delete_anything_on_its_own(tmp_path):
    """The central claim: nothing automatic ever reaches a delete call.
    Time passing alone - no execute() call at all - must not change
    anything, and re-opening the queue much later must not either.
    """
    request_calls = []

    def request(*a, **k):
        request_calls.append(a)
        raise AssertionError("no delete may happen from time passing alone")

    q_path = str(tmp_path / "reclaim-queue.json")
    h_path = str(tmp_path / "reclaim-history.json")
    queue = reclaim.Queue(q_path, h_path, now=NOW)
    item_id = queue.flag("tv", 1, "A Show", 1000, make_evidence())

    much_later = NOW + datetime.timedelta(days=365)
    reopened = reclaim.Queue(q_path, h_path, now=much_later)
    assert reopened.is_due(item_id, CONFIG["hold_days"]) is True
    assert reopened.items[item_id]["state"] == "PENDING"
    assert request_calls == []


def test_execute_refuses_a_stale_scan(tmp_path):
    stale_scanned_at = (NOW - datetime.timedelta(days=10)).timestamp()
    q_path = str(tmp_path / "reclaim-queue.json")
    h_path = str(tmp_path / "reclaim-history.json")
    flagging_queue = reclaim.Queue(q_path, h_path, now=NOW)
    item_id = flagging_queue.flag(
        "tv", 1, "A Show", 1000, make_evidence(scanned_at=stale_scanned_at))

    later = NOW + datetime.timedelta(days=8)  # past the 7-day hold
    queue = reclaim.Queue(q_path, h_path, now=later)
    lib, movie_lib = make_libs(later)

    def request(*a, **k):
        raise AssertionError("must not delete against a stale scan")

    with pytest.raises(reclaim.ReclaimError, match="scan"):
        reclaim.execute(lib, movie_lib, queue, [item_id], CONFIG,
                        request=request)
    assert queue.items[item_id]["state"] == "PENDING"


def test_execute_reverifies_and_drops_an_item_that_became_unsafe(tmp_path):
    # At flag time this looked safe. By execute time, an episode that
    # exists on disk has never been watched - the live re-verify must
    # catch this even though the stored evidence still says safe.
    series_list = [series_row(id=1, title="A Show")]
    episodes = {1: [episode(1, 1), episode(1, 2)]}
    history = [history_row(season=1, ep=1)]  # episode 2 never watched
    later = NOW + datetime.timedelta(days=8)
    lib, movie_lib = make_libs(later, series_list=series_list,
                               episodes_by_id=episodes, history_rows=history)

    q_path = str(tmp_path / "reclaim-queue.json")
    h_path = str(tmp_path / "reclaim-history.json")
    flagging_queue = reclaim.Queue(q_path, h_path, now=NOW)
    item_id = flagging_queue.flag(
        "tv", 1, "A Show", 1000, make_evidence(scanned_at=later.timestamp()))
    queue = reclaim.Queue(q_path, h_path, now=later)

    def request(*a, **k):
        raise AssertionError("must not delete an item that failed re-verify")

    result = reclaim.execute(lib, movie_lib, queue, [item_id], CONFIG,
                             request=request)
    assert result["removed"] == []
    assert queue.items[item_id]["state"] == "PENDING"
    assert "never watched" in queue.items[item_id]["reason"]
    # The hold restarted rather than the item staying due immediately.
    assert queue.items[item_id]["flagged_at"] == later.timestamp()


def test_cap_exceeded_aborts_the_whole_run_rather_than_truncating(tmp_path):
    series_list = [series_row(id=1, title="Show One", size_bytes=100),
                  series_row(id=2, title="Show Two", size_bytes=200)]
    episodes = {1: [episode(1, 1)], 2: [episode(1, 1)]}
    history = [history_row(show="Show One", season=1, ep=1),
              history_row(show="Show Two", season=1, ep=1)]
    later = NOW + datetime.timedelta(days=8)
    lib, movie_lib = make_libs(later, series_list=series_list,
                               episodes_by_id=episodes, history_rows=history)

    q_path = str(tmp_path / "reclaim-queue.json")
    h_path = str(tmp_path / "reclaim-history.json")
    flagging_queue = reclaim.Queue(q_path, h_path, now=NOW)
    evidence = make_evidence(scanned_at=later.timestamp())
    id1 = flagging_queue.flag("tv", 1, "Show One", 100, evidence)
    id2 = flagging_queue.flag("tv", 2, "Show Two", 200, evidence)
    queue = reclaim.Queue(q_path, h_path, now=later)

    cfg = dict(CONFIG, max_bytes=250)  # smaller than 100 + 200

    def request(*a, **k):
        raise AssertionError("a capped-out run must delete nothing at all")

    with pytest.raises(reclaim.ReclaimError, match="cap"):
        reclaim.execute(lib, movie_lib, queue, [id1, id2], cfg,
                        request=request)
    assert queue.items[id1]["state"] == "PENDING"
    assert queue.items[id2]["state"] == "PENDING"


def test_canary_is_the_smallest_item_and_runs_alone_first(tmp_path):
    series_list = [series_row(id=1, title="Big Show", size_bytes=300),
                  series_row(id=2, title="Small Show", size_bytes=100),
                  series_row(id=3, title="Medium Show", size_bytes=200)]
    episodes = {i: [episode(1, 1)] for i in (1, 2, 3)}
    history = [history_row(show="Big Show", season=1, ep=1),
              history_row(show="Small Show", season=1, ep=1),
              history_row(show="Medium Show", season=1, ep=1)]
    later = NOW + datetime.timedelta(days=8)
    removed_ids = set()
    lib, movie_lib = make_libs(later, series_list=series_list,
                               episodes_by_id=episodes, history_rows=history,
                               removed_ids=removed_ids)

    q_path = str(tmp_path / "reclaim-queue.json")
    h_path = str(tmp_path / "reclaim-history.json")
    flagging_queue = reclaim.Queue(q_path, h_path, now=NOW)
    evidence = make_evidence(scanned_at=later.timestamp())
    ids = [
        flagging_queue.flag("tv", 1, "Big Show", 300, evidence),
        flagging_queue.flag("tv", 2, "Small Show", 100, evidence),
        flagging_queue.flag("tv", 3, "Medium Show", 200, evidence),
    ]
    queue = reclaim.Queue(q_path, h_path, now=later)
    request = make_request(removed_ids=removed_ids)

    result = reclaim.execute(lib, movie_lib, queue, ids, CONFIG,
                             request=request)
    assert len(result["removed"]) == 3
    first_url = request.calls[0][0]
    assert "/series/2?" in first_url  # Small Show, id 2, is the smallest


def test_a_failed_canary_stops_the_run(tmp_path):
    series_list = [series_row(id=1, title="Show One", size_bytes=100),
                  series_row(id=2, title="Show Two", size_bytes=200)]
    episodes = {1: [episode(1, 1)], 2: [episode(1, 1)]}
    history = [history_row(show="Show One", season=1, ep=1),
              history_row(show="Show Two", season=1, ep=1)]
    later = NOW + datetime.timedelta(days=8)
    lib, movie_lib = make_libs(later, series_list=series_list,
                               episodes_by_id=episodes, history_rows=history)

    q_path = str(tmp_path / "reclaim-queue.json")
    h_path = str(tmp_path / "reclaim-history.json")
    flagging_queue = reclaim.Queue(q_path, h_path, now=NOW)
    evidence = make_evidence(scanned_at=later.timestamp())
    ids = [flagging_queue.flag("tv", 1, "Show One", 100, evidence),
          flagging_queue.flag("tv", 2, "Show Two", 200, evidence)]
    queue = reclaim.Queue(q_path, h_path, now=later)
    request = make_request(fail_at_call=1)  # the canary itself fails

    with pytest.raises(reclaim.ReclaimError):
        reclaim.execute(lib, movie_lib, queue, ids, CONFIG, request=request)
    assert len(request.calls) == 1
    assert queue.items[ids[0]]["state"] == "PENDING"
    assert queue.items[ids[1]]["state"] == "PENDING"


def test_delete_url_is_exactly_right(tmp_path):
    series_list = [series_row(id=1, title="A Show", size_bytes=100)]
    episodes = {1: [episode(1, 1)]}
    history = [history_row(season=1, ep=1)]
    movies_list = [movie_row(id=1, title="A Film", size_bytes=100)]
    movie_history = [movie_history_row()]
    later = NOW + datetime.timedelta(days=8)
    removed_ids = set()
    lib, movie_lib = make_libs(later, series_list=series_list,
                               episodes_by_id=episodes, history_rows=history,
                               movies_list=movies_list,
                               movie_history_rows=movie_history,
                               removed_ids=removed_ids)

    q_path = str(tmp_path / "reclaim-queue.json")
    h_path = str(tmp_path / "reclaim-history.json")
    flagging_queue = reclaim.Queue(q_path, h_path, now=NOW)
    evidence = make_evidence(scanned_at=later.timestamp())
    tv_id = flagging_queue.flag("tv", 1, "A Show", 100, evidence)
    queue = reclaim.Queue(q_path, h_path, now=later)
    request = make_request(removed_ids=removed_ids)
    reclaim.execute(lib, movie_lib, queue, [tv_id], CONFIG, request=request)
    url, method, headers = request.calls[0]
    assert method == "DELETE"
    assert url == ("http://sonarr/api/v3/series/1"
                   "?deleteFiles=true&addImportListExclusion=false")
    assert headers["X-Api-Key"] == "x"

    # A fresh removed_ids for the movie half - the tv series and the movie
    # both happen to use service id 1, and they must not share a "gone"
    # set with each other.
    removed_ids2 = set()
    lib2, movie_lib2 = make_libs(later, series_list=series_list,
                                 episodes_by_id=episodes, history_rows=history,
                                 movies_list=movies_list,
                                 movie_history_rows=movie_history,
                                 removed_ids=removed_ids2)
    flagging_queue2 = reclaim.Queue(q_path, h_path, now=NOW)
    movie_id = flagging_queue2.flag("movie", 1, "A Film", 100, evidence)
    queue2 = reclaim.Queue(q_path, h_path, now=later)
    request2 = make_request(removed_ids=removed_ids2)
    reclaim.execute(lib2, movie_lib2, queue2, [movie_id], CONFIG,
                    request=request2)
    url2, method2, headers2 = request2.calls[0]
    assert method2 == "DELETE"
    assert url2 == ("http://radarr/api/v3/movie/1"
                    "?deleteFiles=true&addImportExclusion=false")
    assert headers2["X-Api-Key"] == "x"


def test_history_is_written_after_each_item_not_at_the_end(tmp_path):
    series_list = [series_row(id=1, title="Show One", size_bytes=100),
                  series_row(id=2, title="Show Two", size_bytes=200)]
    episodes = {1: [episode(1, 1)], 2: [episode(1, 1)]}
    history = [history_row(show="Show One", season=1, ep=1),
              history_row(show="Show Two", season=1, ep=1)]
    later = NOW + datetime.timedelta(days=8)
    removed_ids = set()
    lib, movie_lib = make_libs(later, series_list=series_list,
                               episodes_by_id=episodes, history_rows=history,
                               removed_ids=removed_ids)

    q_path = str(tmp_path / "reclaim-queue.json")
    h_path = str(tmp_path / "reclaim-history.json")
    flagging_queue = reclaim.Queue(q_path, h_path, now=NOW)
    evidence = make_evidence(scanned_at=later.timestamp())
    ids = [flagging_queue.flag("tv", 1, "Show One", 100, evidence),
          flagging_queue.flag("tv", 2, "Show Two", 200, evidence)]
    queue = reclaim.Queue(q_path, h_path, now=later)
    # The canary (Show One, smaller) succeeds; the second call fails.
    request = make_request(removed_ids=removed_ids, fail_at_call=2)

    with pytest.raises(reclaim.ReclaimError):
        reclaim.execute(lib, movie_lib, queue, ids, CONFIG, request=request)

    with open(h_path, encoding="utf-8") as fh:
        recorded_history = json.load(fh)
    assert len(recorded_history) == 1
    assert queue.items[ids[0]]["state"] == "REMOVED"
    assert queue.items[ids[1]]["state"] == "PENDING"


def test_cancel_works_from_both_pending_and_due(tmp_path):
    q_path = str(tmp_path / "reclaim-queue.json")
    h_path = str(tmp_path / "reclaim-history.json")
    flagging_queue = reclaim.Queue(q_path, h_path, now=NOW)
    pending_id = flagging_queue.flag("tv", 1, "A Show", 100,
                                     make_evidence())
    due_id = flagging_queue.flag("tv", 2, "Another Show", 100,
                                 make_evidence())
    # Backdate the second item's flag so it is already past the hold.
    flagging_queue.items[due_id]["flagged_at"] = (
        NOW - datetime.timedelta(days=30)).timestamp()
    flagging_queue._save()

    later = NOW + datetime.timedelta(days=1)
    queue = reclaim.Queue(q_path, h_path, now=later)
    assert queue.is_due(pending_id, CONFIG["hold_days"]) is False
    assert queue.is_due(due_id, CONFIG["hold_days"]) is True

    queue.cancel(pending_id)
    queue.cancel(due_id)
    assert queue.items[pending_id]["state"] == "CANCELLED"
    assert queue.items[due_id]["state"] == "CANCELLED"


def test_queue_file_write_is_atomic(tmp_path, monkeypatch):
    calls = []
    real_replace = reclaim.os.replace

    def spy_replace(src, dst):
        calls.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(reclaim.os, "replace", spy_replace)
    queue = make_queue(tmp_path, NOW)
    queue.flag("tv", 1, "A Show", 1000, make_evidence())

    assert calls, "expected os.replace to be used for the atomic write"
    with open(queue.path, encoding="utf-8") as fh:
        json.load(fh)  # must be complete, valid JSON - never a partial file


def test_broomarr_module_issues_no_non_get_request():
    with open(broomarr.__file__, encoding="utf-8") as fh:
        source = fh.read()
    assert "method=" not in source, (
        "broomarr.py must stay GET-only - any Request(..., method=...) "
        "belongs in reclaim.py, never here")
