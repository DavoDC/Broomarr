"""Broomarr dry-run report - the reviewable evidence dump for a hand-run.

    python src/dry_run_report.py            write the report to captures/

Read-only, same as broomarr.py itself: this module makes no write call to
any API and touches the filesystem only to write its own report file under
captures/ (gitignored - see .gitignore). It computes no safety decision of
its own. Every safe/blocked call is Library.verdict() from broomarr.py,
unchanged - this module only keeps and formats the evidence scan() already
computes internally but does not print, and sorts it so the calls that most
need a human's attention are not buried under the obvious ones.

scan() in broomarr.py prints a title and a size for each safe candidate,
which is a verdict without its evidence - not enough for someone to judge
the call themselves. This module exists to close that gap before the very
first run against a real library, per docs/IDEAS.md's "Current Focus".

Sort order:
  SAFE TO DELETE   - a show whose last view only just cleared the quiet
                      period (< MARGIN_DAYS_RISKY days to spare) sorts
                      first, regardless of size: that is the closest call
                      verdict() made. Everything else sorts by reclaimed
                      size, largest first, since that is what makes a wrong
                      call expensive.
  BLOCKED           - fewest blocking reasons first: a show one condition
                      away from safe is the one worth a second look, not
                      the show blocked six ways at once. Largest first
                      within a tie.
"""
import datetime
import os
import sys
import time

import broomarr

REPORT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures")

# A "safe" show watched fewer than this many days past the quiet-period
# threshold is flagged as a close call and sorted to the top of SAFE TO
# DELETE, ahead of shows with more room to spare.
MARGIN_DAYS_RISKY = 7


def _gb(series):
    return series["statistics"]["sizeOnDisk"] / 1e9


def _quiet_margin_days(lib, users, watcher):
    """How many days past the quiet-period threshold the watcher's last
    view sits. None if it cannot be computed - which only happens on a
    show verdict() already blocked, so this is only meaningful for the
    safe_items evaluate() collects.
    """
    if watcher is None:
        return None
    last = users[watcher]["last"]
    if not last:
        return None
    days = int((lib.now().timestamp() - last) // broomarr.SECONDS_PER_DAY)
    return days - lib.quiet_days


def evaluate(lib):
    """Run the same two-pass scan scan() runs, keeping full evidence.

    Returns (safe_items, blocked_items, total_series, candidate_count).
    Makes no decision of its own - every safe/blocked split and every
    reason string here comes straight from lib.verdict().
    """
    all_series = lib.series()
    index = lib.watch_index()

    # Same cheap-then-strict structure as broomarr.scan(): only shows the
    # watcher has plausibly finished are worth a per-episode call.
    candidates = []
    for series in all_series:
        users = index.get(series["title"].lower(), {})
        cheap_safe, _ = lib.verdict(series, users, deep=False)
        if cheap_safe:
            candidates.append((series, users))

    safe_items, blocked_items = [], []
    for series, users in candidates:
        ok, reasons = lib.verdict(series, users)

        missing, upcoming, on_disk_eps = [], [], None
        try:
            missing, upcoming, on_disk_eps = lib.episode_facts(series["id"])
        except Exception:
            pass  # verdict() already turned this into a blocking reason.

        watcher = next((n for n in users if lib.matches_watcher(n)), None)
        watched_eps = users[watcher]["eps"] if watcher else set()
        # on_disk_eps is None when episode_facts() could not establish it
        # (the try/except above) - treat that the same as "nothing on disk
        # to verify against" here, since the difference is already a
        # blocking reason on lib.verdict()'s side and this dict only
        # renders evidence, never decides.
        unwatched = sorted((on_disk_eps or set()) - watched_eps)
        last_ts = users[watcher]["last"] if watcher else None

        item = {
            "id": series.get("id"),
            "title": series["title"],
            "tvdb_id": series.get("tvdbId"),
            "size_gb": _gb(series),
            "status": series.get("status"),
            "ended": series.get("ended"),
            "watcher_matched": watcher,
            "last_watched": (
                datetime.datetime.fromtimestamp(last_ts).strftime("%Y-%m-%d")
                if last_ts else None),
            "quiet_margin_days": _quiet_margin_days(lib, users, watcher),
            "episodes_on_disk": len(on_disk_eps) if on_disk_eps is not None else None,
            "episodes_watched": len(watched_eps),
            "missing_episodes": missing,
            "upcoming_episodes": upcoming,
            "unwatched_on_disk": ["S%02dE%02d" % (s, e) for s, e in unwatched],
            "reasons": reasons,
            "safe": ok,
        }
        (safe_items if ok else blocked_items).append(item)

    def safe_sort_key(item):
        margin = item["quiet_margin_days"]
        risky = margin is not None and margin < MARGIN_DAYS_RISKY
        return (0 if risky else 1, -item["size_gb"])

    def blocked_sort_key(item):
        return (len(item["reasons"]), -item["size_gb"])

    safe_items.sort(key=safe_sort_key)
    blocked_items.sort(key=blocked_sort_key)

    return safe_items, blocked_items, len(all_series), len(candidates)


def _render_safe(lib, item):
    lines = []
    lines.append("- %s  (%.1f GB, tvdb %s)"
                 % (item["title"], item["size_gb"], item["tvdb_id"]))
    margin = item["quiet_margin_days"]
    if margin is not None and margin < MARGIN_DAYS_RISKY:
        lines.append("    ** CLOSE CALL: only %d day(s) past the %d-day "
                     "quiet period - look at this one first **"
                     % (margin, lib.quiet_days))
    lines.append("    proposed action : candidate for deletion (Broomarr "
                "does not delete - you would do this in Sonarr)")
    lines.append("    watcher         : %s (matched %r)"
                % (item["watcher_matched"], lib.watcher))
    lines.append("    last watched    : %s" % (item["last_watched"] or "unknown"))
    lines.append("    episodes        : %d on disk, all %d watched by %s"
                % (item["episodes_on_disk"], item["episodes_watched"],
                   item["watcher_matched"]))
    lines.append("    series status   : %s (ended: %s)"
                % (item["status"], item["ended"]))
    lines.append("    evidence        : series ended, every aired episode is "
                "on disk, every episode on disk was watched by %s, "
                "nothing upcoming, last view %s the %d-day quiet period"
                % (item["watcher_matched"],
                   "clears" if (margin or 0) >= 0 else "does NOT clear",
                   lib.quiet_days))
    return "\n".join(lines)


def _render_blocked(item):
    lines = []
    lines.append("- %s  (%.1f GB, tvdb %s)"
                 % (item["title"], item["size_gb"], item["tvdb_id"]))
    lines.append("    proposed action : keep - blocked on %d reason(s)"
                % len(item["reasons"]))
    for reason in item["reasons"]:
        lines.append("      - %s" % reason)
    return "\n".join(lines)


def render(lib, safe_items, blocked_items, total_series, candidate_count):
    lines = []
    lines.append("Broomarr dry-run report")
    lines.append("generated %s"
                 % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("watcher=%r  quiet_days=%d" % (lib.watcher, lib.quiet_days))
    lines.append("")
    lines.append("This report never deletes anything. Everything below is "
                 "a proposal for you to review; nothing has been changed "
                 "on disk or in Sonarr. Delete through Sonarr by hand, or "
                 "flag a candidate in the GUI's Hold Queue to remove it "
                 "after a confirmed hold.")
    lines.append("")
    lines.append("%d series in Sonarr, %d passed the cheap prefilter and "
                 "were examined in full, %d safe, %d blocked."
                 % (total_series, candidate_count, len(safe_items),
                    len(blocked_items)))
    lines.append("")
    lines.append("=" * 72)
    lines.append("SAFE TO DELETE - REVIEW EACH ONE (closest calls first)")
    lines.append("=" * 72)
    if not safe_items:
        lines.append("  nothing")
    for item in safe_items:
        lines.append("")
        lines.append(_render_safe(lib, item))
    total_gb = sum(i["size_gb"] for i in safe_items)
    lines.append("")
    lines.append("%d show(s), %.1f GB if you act on all of them"
                 % (len(safe_items), total_gb))

    if blocked_items:
        lines.append("")
        lines.append("=" * 72)
        lines.append("BLOCKED (informational - closest calls first)")
        lines.append("=" * 72)
        for item in blocked_items:
            lines.append("")
            lines.append(_render_blocked(item))

    lines.append("")
    lines.append("Delete through Sonarr by hand. This report never deletes "
                 "anything.")
    return "\n".join(lines) + "\n"


def main(argv=None):
    start = time.time()
    lib = broomarr.Library(broomarr.load_config())

    print("Broomarr dry-run report: read-only, same decision logic as --all.")
    print("Starting %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    safe_items, blocked_items, total, candidates = evaluate(lib)
    text = render(lib, safe_items, blocked_items, total, candidates)

    print(text)

    os.makedirs(REPORT_DIR, exist_ok=True)
    out_path = os.path.join(
        REPORT_DIR,
        "dry-run-report-%s.txt" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)

    elapsed = time.time() - start
    print("Report written to %s" % out_path)
    print("Elapsed: %.1fs" % elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
