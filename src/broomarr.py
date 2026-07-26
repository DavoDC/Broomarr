"""Broomarr - which TV shows are actually safe to delete?

    python src/broomarr.py --all              scan the whole library
    python src/broomarr.py "Some Show"        explain one show

Asks Sonarr what episodes really exist and Tautulli who watched them, and
joins the two itself. That distinction is the whole point: tools that ask the
media server "has this been fully watched?" only ever learn about episodes
that were downloaded, so a half-fetched series reads as finished. See
docs/DESIGN.md.

The one rule that keeps this safe: an unknown value blocks. Anything that
cannot be established is a reason not to delete, never a check that quietly
does not apply.

Read-only by design, permanently. This must never grow a --delete flag - an
unrun script deletes nothing, which is the entire reason it is safe to rely
on. Deletion stays a deliberate manual action in Sonarr.
"""

import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "config", "config.json")

SECONDS_PER_DAY = 86400


def load_config(path=CONFIG):
    if not os.path.exists(path):
        raise SystemExit(
            "No config at %s\nCopy config/config.example.json to "
            "config/config.json and fill in your API keys." % path)
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    missing = [k for k in ("sonarr_url", "sonarr_api_key",
                           "tautulli_url", "tautulli_api_key", "watcher")
               if not cfg.get(k)]
    if missing:
        raise SystemExit("config.json is missing: %s" % ", ".join(missing))
    cfg.setdefault("quiet_days", 14)
    return cfg


def _to_int(value):
    """Coerce a season/episode identifier to int, or None if it cannot be.

    Tautulli returns these as strings in some API versions and Sonarr
    already returns ints, but both sides are coerced here so the join in
    Library.verdict() compares like with like.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=120) as response:
        body = response.read().decode("utf-8").strip()
    return json.loads(body) if body else None


class Library:
    """Everything Broomarr knows, from the two services that actually know it.

    `fetch` is injectable so the decision logic can be tested without a
    running Sonarr or Tautulli.
    """

    def __init__(self, config, fetch=http_get, now=None):
        self.cfg = config
        self.fetch = fetch
        self._now = now
        self.watcher = config["watcher"]
        self.quiet_days = config["quiet_days"]

    def now(self):
        return self._now or datetime.datetime.now(datetime.timezone.utc)

    def sonarr(self, path):
        return self.fetch(self.cfg["sonarr_url"].rstrip("/") + path,
                          {"X-Api-Key": self.cfg["sonarr_api_key"]})

    def tautulli(self, cmd, **params):
        query = "".join("&%s=%s" % (k, urllib.parse.quote(str(v)))
                        for k, v in params.items())
        url = "%s/api/v2?apikey=%s&cmd=%s%s" % (
            self.cfg["tautulli_url"].rstrip("/"),
            self.cfg["tautulli_api_key"], cmd, query)
        return self.fetch(url)["response"]["data"]

    def series(self):
        return self.sonarr("/api/v3/series")

    def watch_index(self, titles=None):
        """Distinct episodes watched per show per user, from Tautulli history.

        Returns {show_title_lower: {user: {"eps": set(), "last": epoch}}}.
        One bulk call rather than one per show.
        """
        rows = self.tautulli("get_history", media_type="episode",
                             length=50000)["data"]
        index = {}
        for row in rows:
            show = (row.get("grandparent_title") or "").strip()
            if not show or (titles is not None and show.lower() not in titles):
                continue
            # Tautulli records a partial view as history; require a real watch.
            if (row.get("watched_status") or 0) < 0.5:
                continue
            # A row whose season/episode cannot be identified must not
            # silently count as a watched episode - unknown blocks.
            season = _to_int(row.get("parent_media_index"))
            ep = _to_int(row.get("media_index"))
            if season is None or ep is None:
                continue
            user = index.setdefault(show.lower(), {}).setdefault(
                row["friendly_name"], {"eps": set(), "last": 0})
            user["eps"].add((season, ep))
            user["last"] = max(user["last"], row.get("stopped") or 0)
        return index

    def episode_facts(self, series_id):
        """Sonarr's real episode list, ignoring specials (season 0).

        Returns (missing, upcoming, on_disk_eps): aired but not downloaded,
        not yet aired, and the (season, episode) identifiers of every
        aired episode that has a file. Counting from the episode list
        rather than from the series statistics avoids two separate traps -
        see docs/DESIGN.md.
        """
        now = self.now()
        missing, upcoming, on_disk_eps = [], [], set()
        for episode in self.sonarr("/api/v3/episode?seriesId=%s" % series_id):
            season = episode.get("seasonNumber", 0)
            if season == 0:
                continue
            aired = False
            air_date = episode.get("airDateUtc")
            if air_date:
                try:
                    aired = datetime.datetime.fromisoformat(
                        air_date.replace("Z", "+00:00")) <= now
                except ValueError:
                    aired = False
            label = "S%02dE%02d" % (season, episode.get("episodeNumber", 0))
            if not aired:
                upcoming.append(label)
            elif not episode.get("hasFile"):
                # Deliberately NOT filtered by episode["monitored"]. An
                # unmonitored episode is one Sonarr will not fetch - it is
                # still an episode nobody can watch, and Sonarr's own
                # episodeCount excludes it, which is exactly how a series
                # missing an entire season reads as complete.
                missing.append(label)
            else:
                # Sonarr already returns ints here; coerce anyway so both
                # sides of the join in verdict() are guaranteed comparable.
                on_disk_eps.add((_to_int(season),
                                _to_int(episode.get("episodeNumber"))))
        return missing, upcoming, on_disk_eps

    def verdict(self, series, users, deep=True):
        """Is this show safe to delete? Returns (safe, [reasons it is not]).

        Unknown blocks. Every path that cannot establish a fact returns a
        reason rather than passing.
        """
        reasons = []

        if not users:
            return False, ["no watch history at all - "
                           "cannot confirm anyone finished it"]

        watcher = next((n for n in users
                        if self.watcher.lower() in n.lower()), None)
        if watcher is None:
            return False, ["%s has no watch history for this show"
                           % self.watcher]

        last = users[watcher]["last"]
        if not last:
            reasons.append("no last-view timestamp - "
                           "cannot apply the quiet period")
        else:
            days = int((self.now().timestamp() - last) // SECONDS_PER_DAY)
            if days < self.quiet_days:
                reasons.append("watched %d days ago - inside the %d-day "
                               "quiet period" % (days, self.quiet_days))

        if not series.get("ended"):
            reasons.append("still airing (%s) - more episodes are coming"
                           % series.get("status"))

        if deep:
            try:
                missing, upcoming, on_disk_eps = self.episode_facts(series["id"])
            except Exception as exc:
                return False, reasons + [
                    "could not read episode list from Sonarr: %s" % exc]
            if missing:
                reasons.append("%d aired episode(s) never downloaded: %s"
                               % (len(missing), ", ".join(missing[:6])
                                  + (" ..." if len(missing) > 6 else "")))
            if upcoming:
                reasons.append("%d episode(s) not yet aired" % len(upcoming))
            unwatched = sorted(on_disk_eps - users[watcher]["eps"])
            if unwatched:
                labels = ["S%02dE%02d" % (s, e) for s, e in unwatched]
                reasons.append(
                    "%s never watched %d episode(s) on disk: %s"
                    % (self.watcher, len(unwatched), ", ".join(labels[:6])
                       + (" ..." if len(labels) > 6 else "")))
        # else (deep=False): the cheap prefilter in scan() deliberately
        # skips all of the above rather than approximating it with a
        # count. It is only safe because it is *structurally* a weaker
        # predicate than the strict pass - the same function with the
        # episode-list conditions skipped, never a different or
        # approximate test. A count-based approximation (comparing
        # episodeCount to episodeFileCount) can disagree with the strict
        # pass and block a show the strict pass would have passed,
        # silently dropping it from the scan. Permissiveness must be true
        # by construction, not by assertion.

        return (not reasons), reasons


def explain(lib, series, users):
    stats = series["statistics"]
    print("=" * 72)
    print("%s   (tvdb %s)" % (series["title"], series.get("tvdbId")))
    print("=" * 72)
    print()
    print("SONARR")
    print("  status            : %s (finished airing: %s)"
          % (series.get("status"), series.get("ended")))
    print("  episodes on disk  : %s of %s aired"
          % (stats["episodeFileCount"], stats["episodeCount"]))
    print("  size on disk      : %.1f GB" % (stats["sizeOnDisk"] / 1e9))
    try:
        missing, upcoming, _ = lib.episode_facts(series["id"])
        print("  never downloaded  : %s"
              % (", ".join(missing) if missing else "none"))
        print("  not yet aired     : %d" % len(upcoming))
    except Exception as exc:
        print("  episode list      : UNAVAILABLE (%s)" % exc)
    print()
    print("TAUTULLI")
    if not users:
        print("  no watch history found for this title")
    for name, user in sorted(users.items(), key=lambda kv: -len(kv[1]["eps"])):
        when = (datetime.datetime.fromtimestamp(user["last"]).strftime("%Y-%m-%d")
                if user["last"] else "unknown")
        print("  %-22s %3d distinct episodes, last viewed %s"
              % (name, len(user["eps"]), when))
    print()
    safe, reasons = lib.verdict(series, users)
    if safe:
        print("VERDICT: safe to delete - %s finished every episode that "
              "exists," % lib.watcher)
        print("         the series has ended, and nothing is missing or pending.")
    else:
        print("VERDICT: DO NOT DELETE")
        for reason in reasons:
            print("  - %s" % reason)
    print()


def scan(lib):
    print("Scanning library. Sonarr for what exists, Tautulli for who watched it.")
    all_series = lib.series()
    index = lib.watch_index()
    print("  %d series in Sonarr, %d with watch history\n"
          % (len(all_series), len(index)))

    # Cheap pass first: only shows the watcher has plausibly finished are
    # worth a per-episode call. Everything else is not a candidate anyway.
    candidates = []
    for series in all_series:
        users = index.get(series["title"].lower(), {})
        cheap_safe, _ = lib.verdict(series, users, deep=False)
        if cheap_safe:
            candidates.append((series, users))

    safe_list, blocked = [], []
    for series, users in candidates:
        ok, reasons = lib.verdict(series, users)
        (safe_list if ok else blocked).append((series, reasons))

    print("=" * 72)
    print("SAFE TO DELETE")
    print("=" * 72)
    if not safe_list:
        print("  nothing")
    for series, _ in sorted(safe_list,
                            key=lambda x: -x[0]["statistics"]["sizeOnDisk"]):
        print("  %-45s %7.1f GB" % (series["title"][:45],
                                    series["statistics"]["sizeOnDisk"] / 1e9))
    total = sum(s["statistics"]["sizeOnDisk"] for s, _ in safe_list) / 1e9
    print("\n  %d show(s), %.1f GB" % (len(safe_list), total))

    if blocked:
        print()
        print("=" * 72)
        print("LOOKED FINISHED, BLOCKED ON A CLOSER LOOK")
        print("=" * 72)
        print("  These are the ones a count-based rule would get wrong.\n")
        for series, reasons in blocked:
            print("  %s" % series["title"])
            for reason in reasons:
                print("      - %s" % reason)
    print("\nDelete through Sonarr by hand. Broomarr never deletes anything.")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 1

    lib = Library(load_config())

    if argv[0] == "--all":
        scan(lib)
        return 0

    wanted = " ".join(argv).lower()
    matches = [s for s in lib.series() if wanted in s["title"].lower()]
    if not matches:
        print("No Sonarr series matching %r" % wanted)
        return 1
    index = lib.watch_index({s["title"].lower() for s in matches})
    for series in matches:
        explain(lib, series, index.get(series["title"].lower(), {}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
