"""Broomarr - which TV shows and movies are actually safe to delete?

    python src/broomarr.py --check            check config against every configured service
    python src/broomarr.py --all              scan TV, and movies if Radarr is configured
    python src/broomarr.py --movies           scan movies only (needs radarr_url/radarr_api_key)
    python src/broomarr.py "Some Show"        explain one show

USAGE below is the user-facing text for --help and bare invocation. Keep
this docstring in step with it.

Asks Sonarr what episodes really exist, Radarr what movies really exist, and
Tautulli who watched them, and joins the two itself. That distinction is the
whole point: tools that ask the media server "has this been fully watched?"
only ever learn about episodes that were downloaded, so a half-fetched
series reads as finished. See docs/References/DevContext.md.

The one rule that keeps this safe: an unknown value blocks. Anything that
cannot be established is a reason not to delete, never a check that quietly
does not apply. Radarr is optional - config.json without radarr_url/
radarr_api_key simply skips the movie side; --movies and the movie half of
--all otherwise use the same MovieLibrary.verdict() joining on (title, year).

Read-only by design, permanently. This must never grow a --delete flag - an
unrun script deletes nothing, which is the entire reason it is safe to rely
on. Deletion stays a deliberate manual action in Sonarr or Radarr.
"""

import collections
import datetime
import json
import os
import sys
import urllib.error
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
    # Radarr is optional, but only as a pair - one key without the other is
    # a config that looks configured and silently never scans movies.
    has_radarr_url = bool(cfg.get("radarr_url"))
    has_radarr_key = bool(cfg.get("radarr_api_key"))
    if has_radarr_url != has_radarr_key:
        raise SystemExit(
            "config.json has radarr_url without radarr_api_key (or the "
            "other way round) - set both to enable movies, or neither.")
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


# Everything a bad connection, a bad response body or a bad response shape
# can raise out of fetch(). urllib.error.URLError already covers HTTPError
# (it is a subclass), and both are themselves OSError subclasses, but all
# four are listed to say plainly what is being guarded against.
SERVICE_ERRORS = (urllib.error.URLError, urllib.error.HTTPError, OSError,
                  ValueError, KeyError)


class UnreadableFacts(Exception):
    """Raised by episode_facts()/movie_facts() when a response establishes
    nothing about the real state of a series or movie - None, the wrong
    shape, or (for episodes) a real series that came back with zero
    episodes. Distinct from "the show genuinely has none": a real Sonarr
    series always has at least one episode record, so an empty list is a
    failure to answer, not an answer. See docs/References/DevContext.md.
    """


def matches_watcher(watcher, name):
    """The one matching rule for "is this Tautulli friendly name the
    configured watcher" - case-insensitive substring. Module-level so
    Library (TV) and MovieLibrary (movies) share exactly one copy; a fix
    to the rule cannot drift between the two sides.
    """
    return watcher.lower() in name.lower()


# Radarr statuses this side actually recognises. Anything else - a status
# Radarr adds later, or a bad response - blocks as unrecognised rather
# than being treated as "not released" by a fallback default. Only
# "released" ever counts as released; "inCinemas" is deliberately treated
# the same as "announced" here, because a cinema release is not the
# release this tool cares about - a digital/disk copy can still be coming.
RECOGNISED_MOVIE_STATUSES = ("announced", "inCinemas", "released")


def _movie_key(obj):
    """The two-part join key for movies: (lowercased title, year) - never
    title alone, since two different films can share a title. Works for
    both a Radarr movie dict and a Tautulli history row; both carry
    "title" and "year". Returns None if the title is missing or the year
    does not coerce to int, so a row that cannot be keyed is skipped
    rather than joined to the wrong film - see _to_int().
    """
    title = obj.get("title")
    year = _to_int(obj.get("year"))
    if not title or year is None:
        return None
    return (title.strip().lower(), year)


MovieFacts = collections.namedtuple("MovieFacts", ["on_disk", "released"])


def _wrap_service_error(service, base_url, exc):
    """Turn a low-level connection/parsing failure into a message a human
    can act on: which service, the configured base URL (never an API key -
    Sonarr's key travels in a header and is never in base_url; Tautulli's
    key is only ever appended to a per-call query string, never present in
    the configured base_url printed here), and what to check.
    """
    return OSError(
        "%s at %s did not respond as expected (%s: %s). Check the URL is "
        "correct, that %s is running, and the API key in config.json."
        % (service, base_url, type(exc).__name__, exc, service))


class _ServiceClient:
    """Shared config/fetch/now setup and the Tautulli client - Library (TV)
    and MovieLibrary (movies) are otherwise independent, but querying
    Tautulli and knowing "is this my watcher" must not have two copies.

    `fetch` is injectable so the decision logic can be tested without a
    running Sonarr, Radarr or Tautulli.
    """

    def __init__(self, config, fetch=http_get, now=None):
        self.cfg = config
        self.fetch = fetch
        self._now = now
        self.watcher = config["watcher"]
        self.quiet_days = config["quiet_days"]

    def now(self):
        return self._now or datetime.datetime.now(datetime.timezone.utc)

    def tautulli(self, cmd, **params):
        query = "".join("&%s=%s" % (k, urllib.parse.quote(str(v)))
                        for k, v in params.items())
        url = "%s/api/v2?apikey=%s&cmd=%s%s" % (
            self.cfg["tautulli_url"].rstrip("/"),
            self.cfg["tautulli_api_key"], cmd, query)
        try:
            return self.fetch(url)["response"]["data"]
        except SERVICE_ERRORS as exc:
            raise _wrap_service_error(
                "Tautulli", self.cfg["tautulli_url"], exc) from exc

    def matches_watcher(self, name):
        """Shared by verdict() and the config-sanity checks in scan() and
        check() so a fix to the rule cannot drift between call sites.
        """
        return matches_watcher(self.watcher, name)


class Library(_ServiceClient):
    """Everything Broomarr knows about TV, from Sonarr and Tautulli."""

    def sonarr(self, path):
        try:
            return self.fetch(self.cfg["sonarr_url"].rstrip("/") + path,
                              {"X-Api-Key": self.cfg["sonarr_api_key"]})
        except SERVICE_ERRORS as exc:
            raise _wrap_service_error(
                "Sonarr", self.cfg["sonarr_url"], exc) from exc

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
        aired episode that has a file - or None for on_disk_eps on any path
        that did not establish it. Counting from the episode list rather
        than from the series statistics avoids two separate traps - see
        docs/References/DevContext.md.

        Raises UnreadableFacts if the response cannot be trusted at all:
        None, not a list, or a real Sonarr series answering with zero
        episodes. This is a membership/type test, not a truthiness test,
        so the three cases stay distinguishable in the message even though
        all three block.
        """
        now = self.now()
        response = self.sonarr("/api/v3/episode?seriesId=%s" % series_id)
        if response is None:
            raise UnreadableFacts(
                "Sonarr returned no response for series %s's episode list"
                % series_id)
        if not isinstance(response, list):
            raise UnreadableFacts(
                "Sonarr returned a %s, not a list, for series %s's episode "
                "list" % (type(response).__name__, series_id))
        if len(response) == 0:
            raise UnreadableFacts(
                "Sonarr returned no episodes for series %s, which is not "
                "a fact about the series" % series_id)
        missing, upcoming, on_disk_eps = [], [], set()
        for episode in response:
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

        watcher = next((n for n in users if self.matches_watcher(n)), None)
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
            if on_disk_eps is None:
                # Belt-and-braces: episode_facts() raises before returning
                # None today, so this path is not reachable, but the check
                # stays so the contract is self-documenting at the one call
                # site that matters most - a reader sees this and knows
                # emptiness and unreadability are different things here.
                reasons.append("could not establish which episodes are on "
                               "disk")
            elif not on_disk_eps:
                reasons.append("no episodes with files found on disk, "
                               "nothing to verify against.")
            else:
                unwatched = sorted(on_disk_eps - users[watcher]["eps"])
                if unwatched:
                    labels = ["S%02dE%02d" % (s, e) for s, e in unwatched]
                    reasons.append(
                        "%s never watched %d episode(s) on disk: %s"
                        % (self.watcher, len(unwatched),
                           ", ".join(labels[:6])
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


class MovieLibrary(_ServiceClient):
    """Everything Broomarr knows about movies, from Radarr and Tautulli.

    The join is per-instance-cached and two-part: (title, year), never
    title alone - see _movie_key(). A partial view is the whole watch
    signal for a film (there is no per-episode set difference to fall
    back on the way there is on the TV side), so movie_watch_index()
    tracks "started but never finished" as its own distinct state rather
    than collapsing it into "no history".
    """

    def __init__(self, config, fetch=http_get, now=None):
        super().__init__(config, fetch=fetch, now=now)
        self._movies_cache = None

    def radarr(self, path):
        try:
            return self.fetch(self.cfg["radarr_url"].rstrip("/") + path,
                              {"X-Api-Key": self.cfg["radarr_api_key"]})
        except SERVICE_ERRORS as exc:
            raise _wrap_service_error(
                "Radarr", self.cfg["radarr_url"], exc) from exc

    def movies(self):
        """Radarr's bulk movie list, cached for this instance's lifetime -
        _duplicate_keys(), movie_facts() and verdict() all need it and a
        scan should not re-fetch it once per movie.
        """
        if self._movies_cache is None:
            self._movies_cache = self.radarr("/api/v3/movie")
        return self._movies_cache

    def _duplicate_keys(self):
        """(title, year) keys shared by two or more Radarr movies - both
        must block, since the join cannot tell them apart.
        """
        counts = {}
        for movie in self.movies():
            key = _movie_key(movie)
            if key is None:
                continue
            counts[key] = counts.get(key, 0) + 1
        return {key for key, count in counts.items() if count > 1}

    def movie_watch_index(self):
        """Distinct watch state per film per user, from Tautulli history.

        Returns {(title_lower, year): {user: {"watched": bool, "last": epoch}}}.
        "watched" only becomes True on a row with watched_status >= 0.5 -
        Tautulli records a partial view as history too, and for a film
        that partial view is the only signal there is, so it must stay
        visible as "started but never finished" rather than vanish into
        "no history at all". A row whose year will not coerce to int is
        skipped entirely, never counted as watched.
        """
        rows = self.tautulli("get_history", media_type="movie",
                             length=50000)["data"]
        index = {}
        for row in rows:
            key = _movie_key(row)
            if key is None:
                continue
            user = index.setdefault(key, {}).setdefault(
                row["friendly_name"], {"watched": False, "last": 0})
            if (row.get("watched_status") or 0) >= 0.5:
                user["watched"] = True
                user["last"] = max(user["last"], row.get("stopped") or 0)
        return index

    def movie_facts(self, movie_id):
        """MovieFacts for one Radarr movie id, or None if no movie in the
        bulk list has that id - a missing map is None, never a
        MovieFacts of empty/false fields, so a caller cannot mistake "no
        such movie" for "a movie with nothing on disk".
        """
        match = next((m for m in self.movies() if m.get("id") == movie_id),
                     None)
        if match is None:
            return None
        return MovieFacts(on_disk=bool(match.get("hasFile")),
                          released=(match.get("status") == "released"))

    def verdict(self, movie, users):
        """Is this movie safe to delete? Returns (safe, [reasons it is not]).

        Unknown blocks, same as Library.verdict() - every path that
        cannot establish a fact returns a reason rather than passing.
        """
        reasons = []

        try:
            duplicates = self._duplicate_keys()
        except Exception as exc:
            return False, ["could not read movie list from Radarr: %s" % exc]

        key = _movie_key(movie)
        if key is not None and key in duplicates:
            reasons.append("another movie in Radarr and this one share "
                           "this title and year - cannot tell them apart")

        if not movie.get("hasFile"):
            reasons.append("no file on disk")

        status = movie.get("status")
        if status == "released":
            pass
        elif status in RECOGNISED_MOVIE_STATUSES:
            reasons.append("not yet released (status: %s)" % status)
        else:
            reasons.append("unrecognised Radarr status: %r" % status)

        if not users:
            reasons.append("no watch history at all - "
                           "cannot confirm anyone finished it")
        else:
            watcher = next((n for n in users if self.matches_watcher(n)),
                           None)
            if watcher is None:
                reasons.append("%s has no watch history for this movie"
                               % self.watcher)
            elif not users[watcher]["watched"]:
                reasons.append("%s started but never finished this movie"
                               % self.watcher)
            else:
                last = users[watcher]["last"]
                if not last:
                    reasons.append("no last-view timestamp - "
                                   "cannot apply the quiet period")
                else:
                    days = int((self.now().timestamp() - last)
                              // SECONDS_PER_DAY)
                    if days < self.quiet_days:
                        reasons.append(
                            "watched %d days ago - inside the %d-day "
                            "quiet period" % (days, self.quiet_days))

        return (not reasons), reasons


def _friendly_names(index):
    """Every distinct Tautulli friendly name seen across watch_index()."""
    names = set()
    for users in index.values():
        names.update(users.keys())
    return names


def _warn_if_watcher_unmatched(lib, friendly_names):
    """Trap: a wrong `watcher` in config.json is otherwise indistinguishable
    from a genuinely clean library - every show blocks with "no watch
    history for this show" and nothing hints the config, not the library,
    is wrong. Print a loud warning up front instead of failing silently.
    """
    if any(lib.matches_watcher(n) for n in friendly_names):
        return
    names_desc = (", ".join(sorted(friendly_names)) if friendly_names
                  else "(none - Tautulli returned no watch history at all)")
    print("[WARNING] configured watcher %r matches none of the Tautulli "
          "friendly name(s) seen in history: %s" % (lib.watcher, names_desc))
    print("[WARNING] every show will block until config.json's 'watcher' "
          "is corrected.")
    print()


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
        missing, upcoming, on_disk_eps = lib.episode_facts(series["id"])
        print("  never downloaded  : %s"
              % (", ".join(missing) if missing else "none"))
        print("  not yet aired     : %d" % len(upcoming))
        if on_disk_eps is None:
            print("  on disk           : UNAVAILABLE - could not establish "
                  "which episodes have files")
        elif not on_disk_eps:
            print("  on disk           : none - nothing to verify against")
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
    _warn_if_watcher_unmatched(lib, _friendly_names(index))
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


def movie_scan(lib):
    """The movie equivalent of scan(): every Radarr movie through
    MovieLibrary.verdict(), joined to Tautulli history by (title, year).

    No cheap prefilter pass here - unlike per-episode Sonarr calls, the
    Radarr movie list and the Tautulli movie history are each one bulk
    call regardless of how many movies are examined, so there is nothing
    a prefilter would save.
    """
    print("Scanning movie library. Radarr for what exists, Tautulli for "
          "who watched it.")
    movies = lib.movies()
    index = lib.movie_watch_index()
    print("  %d movie(s) in Radarr\n" % len(movies))

    safe_list, blocked = [], []
    for movie in movies:
        key = _movie_key(movie)
        users = index.get(key, {}) if key else {}
        ok, reasons = lib.verdict(movie, users)
        (safe_list if ok else blocked).append((movie, reasons))

    print("=" * 72)
    print("SAFE TO DELETE")
    print("=" * 72)
    if not safe_list:
        print("  nothing")
    for movie, _ in sorted(safe_list,
                           key=lambda x: -x[0].get("sizeOnDisk", 0)):
        print("  %-45s %7.1f GB" % (movie["title"][:45],
                                    movie.get("sizeOnDisk", 0) / 1e9))
    total = sum(m.get("sizeOnDisk", 0) for m, _ in safe_list) / 1e9
    print("\n  %d movie(s), %.1f GB" % (len(safe_list), total))

    if blocked:
        print()
        print("=" * 72)
        print("BLOCKED")
        print("=" * 72)
        for movie, reasons in blocked:
            print("  %s" % movie["title"])
            for reason in reasons:
                print("      - %s" % reason)
    print("\nDelete through Radarr by hand. Broomarr never deletes anything.")


def check(lib, movie_lib=None):
    """Read-only, fast config sanity check: no per-episode calls.

    Confirms Sonarr responds and how many series it sees, confirms Tautulli
    responds and how many distinct friendly names appear in history, and
    states whether the configured watcher matches one of them. This is what
    to run before a first --all - unambiguous about pass or fail on each of
    the three points, never a raw traceback. Also checks Radarr, but only
    when movie_lib is given - i.e. only when radarr_url/radarr_api_key are
    both set in config.json.
    """
    print("Checking config.json against Sonarr and Tautulli.")
    print()
    all_ok = True

    try:
        count = len(lib.series())
        print("[OK]   Sonarr responded - %d series" % count)
    except SERVICE_ERRORS as exc:
        print("[FAIL] %s" % exc)
        all_ok = False

    if movie_lib is not None:
        try:
            count = len(movie_lib.movies())
            print("[OK]   Radarr responded - %d movie(s)" % count)
        except SERVICE_ERRORS as exc:
            print("[FAIL] %s" % exc)
            all_ok = False

    friendly_names = set()
    try:
        friendly_names = _friendly_names(lib.watch_index())
        print("[OK]   Tautulli responded - %d distinct friendly name(s) "
              "in history" % len(friendly_names))
    except SERVICE_ERRORS as exc:
        print("[FAIL] %s" % exc)
        all_ok = False

    if any(lib.matches_watcher(n) for n in friendly_names):
        print("[OK]   watcher %r matches a Tautulli friendly name"
              % lib.watcher)
    else:
        names_desc = (", ".join(sorted(friendly_names)) if friendly_names
                      else "(none seen)")
        print("[FAIL] watcher %r matches none of the friendly name(s) "
              "seen: %s" % (lib.watcher, names_desc))
        all_ok = False

    print()
    print("PASS - config.json looks correct." if all_ok else
          "FAIL - fix the item(s) above before running --all.")
    return all_ok


USAGE = """\
Broomarr - which TV shows and movies are actually safe to delete?

  python src/broomarr.py --all              scan TV, and movies if Radarr is configured
  python src/broomarr.py --movies           scan movies only (needs radarr_url/radarr_api_key)
  python src/broomarr.py "Some Show"        explain one show
  python src/broomarr.py --check            check config.json against every configured service
  python src/broomarr.py --help             show this message

Broomarr never deletes anything. It only ever prints a list; you delete
through Sonarr or Radarr yourself.
"""


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(USAGE)
        return 1
    if argv[0] in ("--help", "-h"):
        print(USAGE)
        return 0

    cfg = load_config()
    lib = Library(cfg)
    movie_lib = MovieLibrary(cfg) if cfg.get("radarr_url") else None

    if argv[0] == "--check":
        return 0 if check(lib, movie_lib) else 1

    try:
        if argv[0] == "--all":
            scan(lib)
            if movie_lib is not None:
                print()
                movie_scan(movie_lib)
            return 0

        if argv[0] == "--movies":
            if movie_lib is None:
                print("[ERROR] Radarr is not configured in config.json - "
                      "set radarr_url and radarr_api_key to use --movies.")
                return 1
            movie_scan(movie_lib)
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
    except SERVICE_ERRORS as exc:
        print("[ERROR] %s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
