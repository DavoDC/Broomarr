"""Broomarr's reclaim path - the staged hold queue and the delete calls.

This is the only module in Broomarr that can write to Sonarr or Radarr.
`broomarr.py` stays read-only forever; this module imports it and calls
`Library.verdict()` / `MovieLibrary.verdict()`, never the other way round.
See docs/design/reclaim-backend-design.md section 3 for the full design
this file implements, including why each of the seven interlocks in
execute() exists.

The state machine has three stored states - PENDING, CANCELLED, REMOVED.
"DUE" is never stored: it is computed at query time from flagged_at plus
hold_days, so nothing is running when nobody is looking at the queue.
Nothing here is reachable without a human calling flag() and then, later
and separately, execute() - there is no scheduler, no cron entry and no
background thread anywhere in this file.
"""

import json
import os
import urllib.error
import urllib.request

import broomarr

SECONDS_PER_DAY = broomarr.SECONDS_PER_DAY

DEFAULT_HOLD_DAYS = 7
DEFAULT_MAX_SCAN_AGE_DAYS = 3
DEFAULT_MAX_ITEMS = 10
DEFAULT_MAX_BYTES = 250_000_000_000  # 250 GB


class ReclaimError(Exception):
    """Raised to abort an entire execute() run. Every raise site names
    which interlock refused and why - see execute() below.
    """


def _atomic_write_json(path, data):
    """Write JSON to path via a sibling temp file plus os.replace, so a
    crash mid-write leaves either the old file or the new one, never a
    half-written one. Never called with the target file open elsewhere.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp_path, path)


def http_request(url, method, headers=None, payload=None):
    """The one write-capable HTTP call in Broomarr. Deliberately its own
    function rather than a generalisation of broomarr.http_get, so that
    no code path reachable from broomarr.py can issue a non-GET request
    even by accident - see test_broomarr_module_issues_no_non_get_request.
    A 200 or 202 with an empty body is success for both Sonarr and Radarr.
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {},
                                 method=method)
    with urllib.request.urlopen(req, timeout=120) as response:
        body = response.read().decode("utf-8").strip()
    return json.loads(body) if body else None


class Queue:
    """The hold queue, backed by state/reclaim-queue.json, plus the
    append-only removal history at state/reclaim-history.json. Both files
    are written atomically - see _atomic_write_json().
    """

    def __init__(self, queue_path, history_path, now=None):
        self.path = queue_path
        self.history_path = history_path
        self._now = now
        self.items = {}
        self._next_id = 1
        self._dirty_ids = set()
        self._load()

    def now(self):
        if self._now is not None:
            return self._now
        import datetime
        return datetime.datetime.now(datetime.timezone.utc)

    def _load(self):
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.items = data.get("items", {})
        self._next_id = data.get("next_id", 1)

    def _save(self):
        """Reload-then-merge, not a blind overwrite. NiceGUI hands out a
        fresh Queue per open browser tab over the same file (see
        gui/data.Data.queue()), so this instance's in-memory self.items
        can already be stale by the time it saves. Re-reading the file
        immediately before writing and merging only the items THIS
        instance itself changed - tracked in self._dirty_ids by flag(),
        cancel(), return_to_pending() and mark_removed() - means a
        concurrent writer's change to a different item is never silently
        discarded. next_id only ever grows, so two instances flagging
        around the same time still land on distinct ids.
        """
        on_disk_items, on_disk_next_id = {}, 1
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as fh:
                on_disk = json.load(fh)
            on_disk_items = on_disk.get("items", {})
            on_disk_next_id = on_disk.get("next_id", 1)

        merged_items = dict(on_disk_items)
        for item_id in self._dirty_ids:
            merged_items[item_id] = self.items[item_id]
        merged_next_id = max(self._next_id, on_disk_next_id)

        _atomic_write_json(self.path,
                           {"items": merged_items, "next_id": merged_next_id})
        self.items = merged_items
        self._next_id = merged_next_id

    def flag(self, kind, service_id, title, size_bytes, evidence):
        """Add one item to the queue as PENDING. Writes no request to any
        service - flagging is purely local state. Returns the new item id.
        """
        item_id = str(self._next_id)
        self._next_id += 1
        self.items[item_id] = {
            "kind": kind,
            "service_id": service_id,
            "title": title,
            "size_bytes": size_bytes,
            "flagged_at": self.now().timestamp(),
            "evidence": evidence,
            "state": "PENDING",
            "reason": None,
        }
        self._dirty_ids.add(item_id)
        self._save()
        return item_id

    def is_due(self, item_id, hold_days):
        """True once the hold has elapsed for a still-PENDING item. Never
        true for a cancelled or already-removed item - those are not
        offerable at all, due or not.
        """
        record = self.items[item_id]
        if record["state"] != "PENDING":
            return False
        elapsed = self.now().timestamp() - record["flagged_at"]
        return elapsed >= hold_days * SECONDS_PER_DAY

    def cancel(self, item_id):
        """Cancel works the same way from PENDING or DUE - DUE is not a
        stored state, so there is nothing extra to check here at all.
        Always one click, never a confirmation.
        """
        self.items[item_id]["state"] = "CANCELLED"
        self._dirty_ids.add(item_id)
        self._save()

    def return_to_pending(self, item_id, reason):
        """An item that failed live re-verification goes back to PENDING
        with the new reason and a restarted hold - see execute() interlock 3.
        """
        record = self.items[item_id]
        record["state"] = "PENDING"
        record["reason"] = reason
        record["flagged_at"] = self.now().timestamp()
        self._dirty_ids.add(item_id)
        self._save()

    def mark_removed(self, item_id):
        """Move one item to REMOVED and append it to history, immediately
        after its delete is confirmed - never batched to the end of the
        run. See execute() interlock 7.
        """
        record = self.items[item_id]
        record["state"] = "REMOVED"
        record["removed_at"] = self.now().timestamp()
        self._dirty_ids.add(item_id)
        self._save()
        history = []
        if os.path.exists(self.history_path):
            with open(self.history_path, encoding="utf-8") as fh:
                history = json.load(fh)
        history.append(dict(record, item_id=item_id))
        _atomic_write_json(self.history_path, history)


def _fetch_single(lib, movie_lib, record):
    """Re-read one item's own record directly from Sonarr or Radarr - not
    the bulk list, so a delete that already happened is visible as gone
    rather than served from a cache. Returns None if the service reports
    the record as no longer found - a 404, whether from a delete that
    already happened or a record that never existed.

    Calls lib.fetch()/movie_lib.fetch() directly rather than going
    through Library.sonarr()/MovieLibrary.radarr(), because those wrap
    every SERVICE_ERRORS entry (urllib.error.HTTPError included) into a
    generic OSError via _wrap_service_error(), which throws away the
    HTTP status code a 404 needs to be told apart from every other kind
    of failure. Anything other than a 404 still raises - as ReclaimError,
    never a bare OSError, so gui/main.py's do_execute() (which only
    catches ReclaimError) can show the user something instead of nothing.
    """
    if record["kind"] == "tv":
        client, service = lib, "Sonarr"
        base_url = lib.cfg["sonarr_url"]
        url = base_url.rstrip("/") + "/api/v3/series/%s" % record["service_id"]
        headers = {"X-Api-Key": lib.cfg["sonarr_api_key"]}
    else:
        client, service = movie_lib, "Radarr"
        base_url = movie_lib.cfg["radarr_url"]
        url = base_url.rstrip("/") + "/api/v3/movie/%s" % record["service_id"]
        headers = {"X-Api-Key": movie_lib.cfg["radarr_api_key"]}
    try:
        return client.fetch(url, headers)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise ReclaimError(
            "could not re-read %r from %s immediately before delete: %s"
            % (record["title"], service, exc)) from exc
    except broomarr.SERVICE_ERRORS as exc:
        raise ReclaimError(
            "could not re-read %r from %s immediately before delete: %s"
            % (record["title"], service, exc)) from exc


def _reverify(lib, movie_lib, record):
    """Re-run verdict() against live Sonarr/Radarr and Tautulli data right
    now, from scratch - the whole reason the hold exists is that this can
    disagree with the evidence captured at flag time. See interlock 3.
    """
    if record["kind"] == "tv":
        series = next((s for s in lib.series()
                       if s["id"] == record["service_id"]), None)
        if series is None:
            return False, ["no longer found in Sonarr"]
        index = lib.watch_index()
        users = index.get(series["title"].lower(), {})
        return lib.verdict(series, users)
    movie = next((m for m in movie_lib.movies()
                 if m["id"] == record["service_id"]), None)
    if movie is None:
        return False, ["no longer found in Radarr"]
    index = movie_lib.movie_watch_index()
    key = broomarr._movie_key(movie)
    users = index.get(key, {}) if key is not None else {}
    return movie_lib.verdict(movie, users)


def _delete_url_and_headers(cfg, record):
    if record["kind"] == "tv":
        url = ("%s/api/v3/series/%s?deleteFiles=true"
              "&addImportListExclusion=false"
              % (cfg["sonarr_url"].rstrip("/"), record["service_id"]))
        headers = {"X-Api-Key": cfg["sonarr_api_key"]}
    else:
        url = ("%s/api/v3/movie/%s?deleteFiles=true"
              "&addImportExclusion=false"
              % (cfg["radarr_url"].rstrip("/"), record["service_id"]))
        headers = {"X-Api-Key": cfg["radarr_api_key"]}
    return url, headers


def execute(lib, movie_lib, queue, item_ids, cfg, request=http_request):
    """Run every interlock, in order, then delete. Aborts the whole run
    - raises ReclaimError, deletes nothing - on any interlock failure
    except live re-verification, which instead drops just the items that
    failed it back to PENDING and continues with whatever remains safe.

    Returns {"removed": [item_id, ...]} - the ids actually deleted, in
    the order they were deleted (canary first).
    """
    hold_days = cfg.get("hold_days", DEFAULT_HOLD_DAYS)
    max_scan_age_days = cfg.get("max_scan_age_days", DEFAULT_MAX_SCAN_AGE_DAYS)
    max_items = cfg.get("max_items", DEFAULT_MAX_ITEMS)
    max_bytes = cfg.get("max_bytes", DEFAULT_MAX_BYTES)
    now_ts = queue.now().timestamp()

    # Interlock 1: scan freshness. A verdict computed before the watcher
    # started a rewatch must not be acted on days later.
    for item_id in item_ids:
        record = queue.items[item_id]
        scanned_at = record["evidence"].get("scanned_at")
        if scanned_at is None or (now_ts - scanned_at
                                  > max_scan_age_days * SECONDS_PER_DAY):
            raise ReclaimError(
                "refusing %r: scan backing this item is stale or missing"
                % record["title"])

    # Interlock 2: hold elapsed. The cooling-off period cannot be
    # bypassed by calling execute() directly.
    for item_id in item_ids:
        if not queue.is_due(item_id, hold_days):
            raise ReclaimError(
                "refusing %r: hold period has not elapsed"
                % queue.items[item_id]["title"])

    # Interlock 3: re-verify against live services. Anything that no
    # longer comes back safe is returned to PENDING, with a restarted
    # hold, and excluded from the rest of this run - this is the whole
    # reason the hold exists.
    verified_ids = []
    for item_id in item_ids:
        record = queue.items[item_id]
        try:
            safe, reasons = _reverify(lib, movie_lib, record)
        except Exception as exc:
            safe, reasons = False, ["could not re-verify live: %s" % exc]
        if safe:
            verified_ids.append(item_id)
        else:
            queue.return_to_pending(item_id, "; ".join(reasons))

    if not verified_ids:
        return {"removed": []}

    # Interlock 4: cap. Abort the whole run rather than truncating it -
    # truncating lets sort order pick the victims of a run that was
    # never supposed to happen at this size at all.
    total_bytes = sum(queue.items[i]["size_bytes"] for i in verified_ids)
    if len(verified_ids) > max_items or total_bytes > max_bytes:
        raise ReclaimError(
            "refusing this run: cap exceeded (%d items, %d bytes)"
            % (len(verified_ids), total_bytes))

    # Interlock 5: canary. The smallest item goes alone first; only once
    # it is confirmed gone does the rest of the run proceed.
    ordered_ids = sorted(verified_ids,
                        key=lambda i: queue.items[i]["size_bytes"])

    removed = []
    for position, item_id in enumerate(ordered_ids):
        record = queue.items[item_id]

        # Interlock 6: per-item re-read immediately before the call, in
        # case the record changed since interlock 3 ran.
        current = _fetch_single(lib, movie_lib, record)
        if current is None:
            raise ReclaimError(
                "refusing %r: no longer found immediately before delete"
                % record["title"])

        url, headers = _delete_url_and_headers(cfg, record)
        try:
            request(url, "DELETE", headers=headers)
        except Exception as exc:
            raise ReclaimError("delete failed for %r: %s"
                               % (record["title"], exc)) from exc

        if position == 0:
            # Canary verification: confirm the service actually reports
            # it gone before trusting the rest of the run to the same
            # delete call. A systematically broken call must cost one
            # item, not the whole run.
            still_there = _fetch_single(lib, movie_lib, record)
            if still_there is not None:
                raise ReclaimError(
                    "canary failed: %r still reported present after "
                    "delete - stopping the run" % record["title"])

        # Interlock 7: record immediately, not at the end of the run, so
        # a crash mid-run leaves a truthful account of what is already gone.
        queue.mark_removed(item_id)
        removed.append(item_id)

    return {"removed": removed}
