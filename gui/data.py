"""Everything the GUI needs from broomarr/reclaim, kept out of main.py so
the page-building code stays about layout, not data. No safety decision is
made here - every safe/blocked split and every reason string is
broomarr.Library.verdict() or broomarr.MovieLibrary.verdict(), unchanged.
This module only calls it, formats its output and caches the result to
state/last-scan.json (gitignored) so the GUI never scans on launch - see
docs/design/gui-design.md "No auto-scan on launch".
"""
import datetime
import json
import os
import time

import broomarr
import dry_run_report
import reclaim

from gui import config


def _atomic_write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp_path, path)


def _gather_movies(movie_lib):
    """The movie-side equivalent of dry_run_report.evaluate() - same
    shape of output, so the GUI can treat TV and movie items alike. Every
    safe/blocked decision here is movie_lib.verdict(), unchanged; this
    only packages its output as a dict per movie.
    """
    movies = movie_lib.movies()
    index = movie_lib.movie_watch_index()
    safe_items, blocked_items = [], []
    for movie in movies:
        key = broomarr._movie_key(movie)
        users = index.get(key, {}) if key is not None else {}
        ok, reasons = movie_lib.verdict(movie, users)
        watcher = next((n for n in users if movie_lib.matches_watcher(n)),
                       None)
        item = {
            "id": movie.get("id"),
            "title": movie.get("title"),
            "year": movie.get("year"),
            "size_gb": movie.get("sizeOnDisk", 0) / 1e9,
            "size_bytes": movie.get("sizeOnDisk", 0),
            "status": movie.get("status"),
            "watcher_matched": watcher,
            "reasons": reasons,
            "safe": ok,
        }
        (safe_items if ok else blocked_items).append(item)
    safe_items.sort(key=lambda i: -i["size_gb"])
    blocked_items.sort(key=lambda i: (len(i["reasons"]), -i["size_gb"]))
    return safe_items, blocked_items, len(movies)


class Data:
    """Lazily-created Library/MovieLibrary, plus the cached scan and the
    hold queue. One instance lives for the life of the GUI process.
    """

    def __init__(self):
        self.cfg = None
        self.lib = None
        self.movie_lib = None
        self.last_scan = None

    def ensure_libraries(self):
        if self.cfg is None:
            self.cfg = broomarr.load_config()
            self.lib = broomarr.Library(self.cfg)
            self.movie_lib = (broomarr.MovieLibrary(self.cfg)
                              if self.cfg.get("radarr_url") else None)
        return self.cfg

    def load_cached_scan(self):
        """Read state/last-scan.json without touching any service - what
        the GUI shows on launch, per "no auto-scan on launch".
        """
        if self.last_scan is not None:
            return self.last_scan
        if os.path.exists(config.LAST_SCAN_PATH):
            with open(config.LAST_SCAN_PATH, encoding="utf-8") as fh:
                self.last_scan = json.load(fh)
        return self.last_scan

    def scan_age_days(self):
        scan = self.load_cached_scan()
        if not scan:
            return None
        return (time.time() - scan["scanned_at"]) / broomarr.SECONDS_PER_DAY

    def run_scan(self):
        """A full scan against Sonarr/Radarr/Tautulli, cached to disk.
        Only ever called by the explicit "Re-scan" button - never on page
        load.
        """
        self.ensure_libraries()
        safe, blocked, total_series, candidates = dry_run_report.evaluate(
            self.lib)
        tv = {"safe": safe, "blocked": blocked, "total": total_series,
             "candidates": candidates}

        movies = None
        if self.movie_lib is not None:
            m_safe, m_blocked, m_total = _gather_movies(self.movie_lib)
            movies = {"safe": m_safe, "blocked": m_blocked, "total": m_total}

        self.last_scan = {"scanned_at": time.time(), "tv": tv,
                          "movies": movies}
        _atomic_write_json(config.LAST_SCAN_PATH, self.last_scan)
        return self.last_scan

    def check_health(self):
        """The --check output, as data instead of prints - one (ok, message)
        pair per service, plus the watcher-match line. Never writes
        anything; run on demand from the Dashboard, same as --check itself.
        """
        self.ensure_libraries()
        results = []
        friendly_names = set()
        try:
            count = len(self.lib.series())
            results.append(("Sonarr", True, "%d series" % count))
        except broomarr.SERVICE_ERRORS as exc:
            results.append(("Sonarr", False, str(exc)))
        if self.movie_lib is not None:
            try:
                count = len(self.movie_lib.movies())
                results.append(("Radarr", True, "%d movie(s)" % count))
            except broomarr.SERVICE_ERRORS as exc:
                results.append(("Radarr", False, str(exc)))
        try:
            index = self.lib.watch_index()
            friendly_names = broomarr._friendly_names(index)
            results.append(("Tautulli", True,
                           "%d distinct friendly name(s)"
                           % len(friendly_names)))
        except broomarr.SERVICE_ERRORS as exc:
            results.append(("Tautulli", False, str(exc)))
        watcher_ok = any(self.lib.matches_watcher(n) for n in friendly_names)
        results.append(("watcher %r" % self.lib.watcher, watcher_ok,
                        "matches a Tautulli friendly name" if watcher_ok
                        else "matches nobody seen in history"))
        return results

    def queue(self):
        """A fresh Queue view of state/reclaim-queue.json - cheap, and
        always current, since nothing runs in the background to keep one
        in memory in sync.
        """
        return reclaim.Queue(config.QUEUE_PATH, config.HISTORY_PATH)

    def history(self):
        if not os.path.exists(config.HISTORY_PATH):
            return []
        with open(config.HISTORY_PATH, encoding="utf-8") as fh:
            return json.load(fh)

    def record_removal_actor(self, item_ids, username):
        """Stamp "removed_by" onto the history records for the given item
        ids - called right after a successful reclaim.execute() so an
        attributed history stays a GUI-layer concern, not something
        src/reclaim.py (stdlib-only, no notion of accounts) has to know
        about. Only fills in records that don't already have one, so this
        is safe to call even if it somehow ran twice for the same ids.
        """
        if not item_ids or not os.path.exists(config.HISTORY_PATH):
            return
        with open(config.HISTORY_PATH, encoding="utf-8") as fh:
            history = json.load(fh)
        id_set = set(item_ids)
        changed = False
        for record in history:
            if record.get("item_id") in id_set and "removed_by" not in record:
                record["removed_by"] = username
                changed = True
        if changed:
            _atomic_write_json(config.HISTORY_PATH, history)

    def flag(self, kind, item):
        """Flag one item for the hold queue. Writes only to the local
        queue file - never a request to any service. The evidence snapshot
        carries scanned_at from the scan this item came from, which is
        what reclaim.execute()'s scan-freshness interlock checks later.
        """
        scan = self.load_cached_scan()
        evidence = dict(item, scanned_at=scan["scanned_at"] if scan else None)
        if kind == "tv":
            service_id = item["id"]
            size_bytes = int(item["size_gb"] * 1e9)
        else:
            service_id = item["id"]
            size_bytes = item["size_bytes"]
        return self.queue().flag(kind, service_id, item["title"],
                                 size_bytes, evidence)


def format_age(days):
    if days is None:
        return "not scanned yet"
    if days < 1:
        return "scanned today"
    return "scanned %d day(s) ago" % int(days)
