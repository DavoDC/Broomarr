"""The dry-run report: same verdict() calls scan() makes, full evidence kept.

This module must never compute a safe/blocked verdict itself - every case
here asserts that evaluate() reports exactly what Library.verdict() already
decided, plus the evidence needed to see why. If a test here ever needs its
own safety logic instead of reusing broomarr.Library, that is the bug.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import broomarr
import dry_run_report as report


NOW = datetime.datetime(2026, 7, 26, tzinfo=datetime.timezone.utc)
LONG_AGO = (NOW - datetime.timedelta(days=200)).timestamp()
JUST_CLEARED = (NOW - datetime.timedelta(days=15)).timestamp()  # 1 day past a 14-day quiet period

CONFIG = {
    "sonarr_url": "http://sonarr",
    "sonarr_api_key": "x",
    "tautulli_url": "http://tautulli",
    "tautulli_api_key": "x",
    "watcher": "Watcher",
    "quiet_days": 14,
}


def episode(season, number, has_file=True, aired=True):
    when = NOW - datetime.timedelta(days=30 if aired else -30)
    return {
        "seasonNumber": season,
        "episodeNumber": number,
        "hasFile": has_file,
        "monitored": True,
        "airDateUtc": when.isoformat().replace("+00:00", "Z"),
    }


def series(sid, title, ended=True, on_disk=6, aired_count=6, size_gb=1.0):
    return {
        "id": sid,
        "title": title,
        "tvdbId": sid,
        "status": "ended" if ended else "continuing",
        "ended": ended,
        "statistics": {
            "episodeFileCount": on_disk,
            "episodeCount": aired_count,
            "sizeOnDisk": size_gb * 1e9,
        },
    }


def history_row(show, user="Watcher", season=1, ep=1, watched=1.0, stopped=None):
    return {
        "grandparent_title": show,
        "friendly_name": user,
        "parent_media_index": season,
        "media_index": ep,
        "watched_status": watched,
        "stopped": LONG_AGO if stopped is None else stopped,
    }


def full_library(series_list, episodes_by_id, history_rows):
    """A Library that answers all three endpoints evaluate() touches:
    the series list, the per-series episode list, and Tautulli history -
    dispatched by URL exactly like a real Sonarr/Tautulli would route them.
    """
    def fetch(url, headers=None):
        if "/api/v3/episode" in url:
            sid = int(url.rsplit("=", 1)[1])
            return episodes_by_id[sid]
        if url.startswith(CONFIG["sonarr_url"]):
            return series_list
        return {"response": {"data": {"data": history_rows}}}

    return broomarr.Library(CONFIG, fetch=fetch, now=NOW)


def six_episodes(season=1):
    return [episode(season, n) for n in range(1, 7)]


def watched_rows(show, count, season=1, stopped=None):
    return [history_row(show, season=season, ep=n, stopped=stopped)
            for n in range(1, count + 1)]


def test_evaluate_reuses_verdict_never_recomputes_it():
    """A finished, fully-watched show lands in safe_items with the exact
    reasons (none) that lib.verdict() itself returns - not a second
    opinion computed here.
    """
    lib = full_library(
        [series(1, "Finished Show")],
        {1: six_episodes()},
        watched_rows("Finished Show", 6))

    safe_items, blocked_items, total, candidates = report.evaluate(lib)

    assert total == 1
    assert candidates == 1
    assert len(safe_items) == 1
    assert blocked_items == []
    item = safe_items[0]
    assert item["title"] == "Finished Show"
    assert item["safe"] is True
    assert item["reasons"] == []


def test_blocked_show_carries_its_reasons_verbatim():
    """A show that survives the cheap prefilter (ended, watched, quiet
    period clear) but has an aired episode never downloaded - only the
    deep, per-episode pass can catch this, which is the whole reason the
    tool exists. It must show up here as blocked, with the real reason.
    """
    episodes = six_episodes() + [episode(1, 7, has_file=False)]
    lib = full_library(
        [series(1, "Missing An Episode")],
        {1: episodes},
        watched_rows("Missing An Episode", 6))

    safe_items, blocked_items, _, _ = report.evaluate(lib)

    assert safe_items == []
    assert len(blocked_items) == 1
    assert any("never downloaded" in r for r in blocked_items[0]["reasons"])


def test_report_never_marks_a_blocked_show_safe():
    """Adversarial check: a show with an unwatched episode on disk must
    never appear in safe_items, regardless of sort order or evidence
    formatting bugs.
    """
    lib = full_library(
        [series(1, "Partially Watched")],
        {1: six_episodes()},
        watched_rows("Partially Watched", 3))

    safe_items, blocked_items, _, _ = report.evaluate(lib)

    assert safe_items == []
    assert len(blocked_items) == 1
    assert not blocked_items[0]["safe"]


def test_marginal_quiet_period_sorts_before_a_larger_safe_show():
    """Least-certain-first: a show that only just cleared the quiet period
    is a closer call than a show watched long ago, and must be reviewed
    first even though the other show is bigger.
    """
    lib = full_library(
        [series(1, "Big And Comfortably Safe", size_gb=50.0),
         series(2, "Small But Just Cleared Quiet Period", size_gb=1.0)],
        {1: six_episodes(), 2: six_episodes()},
        watched_rows("Big And Comfortably Safe", 6, stopped=LONG_AGO)
        + watched_rows("Small But Just Cleared Quiet Period", 6, stopped=JUST_CLEARED))

    safe_items, blocked_items, _, _ = report.evaluate(lib)

    assert blocked_items == []
    assert [i["title"] for i in safe_items] == [
        "Small But Just Cleared Quiet Period", "Big And Comfortably Safe"]


def test_safe_items_otherwise_sort_biggest_reclaim_first():
    lib = full_library(
        [series(1, "Small", size_gb=1.0), series(2, "Big", size_gb=90.0)],
        {1: six_episodes(), 2: six_episodes()},
        watched_rows("Small", 6) + watched_rows("Big", 6))

    safe_items, _, _, _ = report.evaluate(lib)

    assert [i["title"] for i in safe_items] == ["Big", "Small"]


def test_blocked_items_sort_fewest_reasons_first():
    """A show blocked on one reason is a closer call than one blocked on
    several, so it belongs above it - worth a second look first. Both
    shows here clear the cheap prefilter (ended, watched, quiet period
    clear) so the difference is purely what the deep episode check finds.
    """
    one_reason = six_episodes() + [episode(1, 7, has_file=False)]
    two_reasons = (six_episodes() + [episode(1, 7, has_file=False)]
                  + [episode(1, 8, has_file=False, aired=False)])
    lib = full_library(
        [series(1, "One Reason"), series(2, "Two Reasons")],
        {1: one_reason, 2: two_reasons},
        watched_rows("One Reason", 6) + watched_rows("Two Reasons", 6))

    safe_items, blocked_items, _, _ = report.evaluate(lib)

    assert safe_items == []
    assert blocked_items[0]["title"] == "One Reason"
    assert len(blocked_items[0]["reasons"]) < len(blocked_items[1]["reasons"])


def test_render_report_includes_evidence_not_just_a_title():
    """The report must show why, not just what - a bare title list is
    exactly what this module exists to avoid.
    """
    lib = full_library(
        [series(1, "Finished Show")],
        {1: six_episodes()},
        watched_rows("Finished Show", 6))
    safe_items, blocked_items, total, candidates = report.evaluate(lib)

    text = report.render(lib, safe_items, blocked_items, total, candidates)

    assert "Finished Show" in text
    assert "Watcher" in text  # who watched it
    assert "quiet period" in text.lower() or "days" in text.lower()
    assert "Delete through Sonarr" in text  # never suggests Broomarr deletes


def test_render_report_never_contains_the_word_deleted():
    """Broomarr never deletes. The report describes what it WOULD do, in
    language that cannot be misread as confirmation something happened.
    """
    lib = full_library(
        [series(1, "Finished Show")],
        {1: six_episodes()},
        watched_rows("Finished Show", 6))
    safe_items, blocked_items, total, candidates = report.evaluate(lib)

    text = report.render(lib, safe_items, blocked_items, total, candidates)

    assert "was deleted" not in text.lower()
    assert "has been deleted" not in text.lower()
