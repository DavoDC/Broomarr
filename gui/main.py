"""Broomarr GUI - NiceGUI app entry point.

Run:  python gui/main.py   (or scripts/run-gui.bat on Windows)

Six tabs behind a left nav, grouped by mutate-vs-observe, per
docs/design/gui-design.md: REVIEW (Dashboard, TV Shows, Movies, Blocked) is
read-only in the strict sense - nothing there can reach a write call to any
service, except flagging, which only ever writes the local hold-queue file.
RECLAIM (Hold Queue, History) is the only group whose code path can issue
an HTTP method other than GET, and that only happens inside reclaim.py,
called from the Hold Queue tab, never anywhere else.

No auto-scan on launch: the page reads the cached scan from
state/last-scan.json and renders instantly with a staleness marker. A scan
only ever runs from the explicit Re-scan button.
"""
from __future__ import annotations

import datetime

from nicegui import ui

from gui import config, data

STORE = data.Data()

NAV_GROUPS = [
    ("REVIEW", ["dashboard", "tv", "movies", "blocked"]),
    ("RECLAIM", ["hold", "history"]),
]

TAB_LABELS = {
    "dashboard": "Dashboard",
    "tv": "TV Shows",
    "movies": "Movies",
    "blocked": "Blocked",
    "hold": "Hold Queue",
    "history": "History",
}

# Colour discipline (docs/design/gui-design.md "Visual system"): red
# appears in exactly one place, the execute control in the Hold Queue.
SAFE_COLOR = "#4caf50"
AMBER_COLOR = "#ffb300"
SLATE_COLOR = "#78909c"
RED_COLOR = "#e53935"


def _card_style(extra=""):
    return ("background:#1e1e1e;border:1px solid #333;border-radius:8px;"
           "padding:12px 16px;" + extra)


def _badge(text, color):
    return ('<span style="background:%s;color:#111;padding:1px 8px;'
           'border-radius:10px;font-size:11px;font-weight:600;">%s</span>'
           % (color, text))


def _build_dashboard(container):
    with container:
        scan = STORE.load_cached_scan()
        age_days = STORE.scan_age_days()

        with ui.row().classes("w-full items-center justify-between"):
            ui.label("Dashboard").classes("text-xl font-bold")
            age_label = ui.label(data.format_age(age_days))
            if age_days is not None and age_days > 3:
                age_label.style("color:%s" % AMBER_COLOR)

            def do_rescan():
                STORE.run_scan()
                ui.notify("Scan complete.")
                build_active_tab()

            ui.button("Re-scan", on_click=do_rescan)

        if not scan:
            with ui.column().style(_card_style()):
                ui.label("The library has not been scanned yet in this "
                        "install. Click Re-scan to run the first one.")
            return

        tv = scan.get("tv") or {}
        movies = scan.get("movies")

        with ui.row().classes("w-full flex-wrap"):
            for value, caption in (
                (tv.get("total", 0), "series in Sonarr"),
                (tv.get("candidates", 0), "candidates (cheap pass)"),
                (len(tv.get("safe", [])), "safe to remove"),
                ("%.1f GB" % sum(i["size_gb"] for i in tv.get("safe", [])),
                 "reclaimable"),
            ):
                with ui.column().style(_card_style("min-width:140px;")):
                    ui.label(str(value)).classes("text-2xl font-bold")
                    ui.label(caption).style("color:#999;font-size:12px;")

        if movies is not None:
            with ui.row().classes("w-full flex-wrap"):
                for value, caption in (
                    (movies.get("total", 0), "movies in Radarr"),
                    (len(movies.get("safe", [])), "safe to remove"),
                    ("%.1f GB"
                     % sum(i["size_gb"] for i in movies.get("safe", [])),
                     "reclaimable"),
                ):
                    with ui.column().style(_card_style("min-width:140px;")):
                        ui.label(str(value)).classes("text-2xl font-bold")
                        ui.label(caption).style("color:#999;font-size:12px;")

        ui.label("SERVICE HEALTH").classes("text-sm font-bold").style(
            "margin-top:16px;color:#999;")

        def do_check():
            health.clear()
            with health:
                for name, ok, detail in STORE.check_health():
                    with ui.row().classes("items-center"):
                        ui.html(_badge("OK", SAFE_COLOR) if ok
                               else _badge("FAIL", RED_COLOR))
                        ui.label("%s - %s" % (name, detail))

        ui.button("Run health check", on_click=do_check).props("outline")
        health = ui.column().classes("w-full")

        ui.label("IN HOLD").classes("text-sm font-bold").style(
            "margin-top:16px;color:#999;")
        pending = [r for r in STORE.queue().items.values()
                  if r["state"] == "PENDING"]
        if pending:
            earliest = min(r["flagged_at"] for r in pending)
            ui.label("%d item(s) flagged. Open the Hold Queue tab to "
                     "review, confirm or cancel." % len(pending))
        else:
            ui.label("Nothing is currently flagged.")


def _reason_badge(safe, reasons):
    if safe:
        return _badge("SAFE", SAFE_COLOR)
    if len(reasons) <= 1:
        return _badge("CLOSE CALL", AMBER_COLOR)
    return _badge("BLOCKED", SLATE_COLOR)


def _build_review_table(container, kind, safe_items, blocked_items,
                        show_all_state):
    with container:
        ui.label(TAB_LABELS[kind]).classes("text-xl font-bold")
        if not safe_items and not blocked_items:
            ui.label("Nothing here yet - run a scan from the Dashboard.")
            return

        show_all = ui.checkbox(
            "Show blocked items too", value=show_all_state[0])

        def on_flag(kind_, item_):
            item_id = STORE.flag(kind_, item_)
            ui.notify("Flagged %r for the hold queue (item %s)."
                      % (item_["title"], item_id))
            render_rows()

        rows_container = ui.column().classes("w-full")

        def render_rows():
            show_all_state[0] = show_all.value
            rows_container.clear()
            with rows_container:
                items = safe_items + (blocked_items if show_all.value else [])
                if not items:
                    ui.label("Nothing is safe to remove right now.")
                    return
                for item in items:
                    with ui.row().classes(
                            "w-full items-center").style(_card_style()):
                        ui.html(_reason_badge(item["safe"], item["reasons"]))
                        with ui.column().style("flex:1;"):
                            title = item["title"]
                            if item.get("year"):
                                title += " (%s)" % item["year"]
                            ui.label(title).classes("font-bold")
                            ui.label("%.1f GB" % item["size_gb"]).style(
                                "color:#999;font-size:12px;")
                        with ui.expansion("evidence").classes("w-full"):
                            if item["safe"]:
                                ui.label("All conditions hold.")
                            else:
                                for reason in item["reasons"]:
                                    ui.label("- %s" % reason)
                        if item["safe"]:
                            ui.button(
                                "Flag for removal",
                                on_click=lambda _, i=item: on_flag(kind, i))

        show_all.on_value_change(lambda _: render_rows())
        render_rows()


def _build_tv(container):
    scan = STORE.load_cached_scan()
    tv = (scan or {}).get("tv") or {}
    _build_review_table(container, "tv", tv.get("safe", []),
                        tv.get("blocked", []), [False])


def _build_movies(container):
    scan = STORE.load_cached_scan()
    movies = (scan or {}).get("movies")
    with container:
        if movies is None:
            ui.label("Movies").classes("text-xl font-bold")
            if STORE.ensure_libraries() and STORE.movie_lib is None:
                ui.label("Radarr is not configured in config.json - "
                        "movies are optional. Set radarr_url and "
                        "radarr_api_key to enable this tab.")
                return
    _build_review_table(container, "movie", (movies or {}).get("safe", []),
                        (movies or {}).get("blocked", []), [False])


def _build_blocked(container):
    with container:
        ui.label("Blocked").classes("text-xl font-bold")
        ui.label("Everything a count-based rule would get wrong. Read-only "
                "- there is no override control here, deliberately.").style(
            "color:#999;")
        scan = STORE.load_cached_scan() or {}
        tv_blocked = (scan.get("tv") or {}).get("blocked", [])
        movie_blocked = ((scan.get("movies") or {}).get("blocked", [])
                        if scan.get("movies") else [])
        all_blocked = sorted(tv_blocked + movie_blocked,
                             key=lambda i: (len(i["reasons"]),
                                           -i["size_gb"]))
        if not all_blocked:
            ui.label("Nothing is blocked - or nothing has been scanned yet.")
            return
        for item in all_blocked:
            with ui.column().style(_card_style()).classes("w-full"):
                ui.label(item["title"]).classes("font-bold")
                for reason in item["reasons"]:
                    ui.label("- %s" % reason)


def _build_hold(container):
    with container:
        ui.label("Hold Queue").classes("text-xl font-bold").style(
            "border-left:3px solid %s;padding-left:8px;" % AMBER_COLOR)
        ui.label("These are flagged, not deleted. Nothing here is removed "
                "by a timer. When the hold elapses you confirm a second "
                "time, or cancel.").style("color:#999;")

        queue = STORE.queue()
        cfg = STORE.ensure_libraries()
        hold_days = cfg.get("hold_days", reclaim_defaults_hold_days())

        pending, due = [], []
        for item_id, record in queue.items.items():
            if record["state"] != "PENDING":
                continue
            (due if queue.is_due(item_id, hold_days) else pending).append(
                (item_id, record))

        ui.label("ON HOLD").classes("text-sm font-bold").style(
            "margin-top:12px;color:#999;")
        if not pending:
            ui.label("Nothing on hold.")
        for item_id, record in pending:
            elapsed_days = ((queue.now().timestamp() - record["flagged_at"])
                           / 86400)
            remaining = max(0, hold_days - elapsed_days)
            with ui.row().classes(
                    "w-full items-center").style(_card_style()):
                with ui.column().style("flex:1;"):
                    ui.label("%s   %.1f GB" % (record["title"],
                                              record["size_bytes"] / 1e9))
                    ui.label("hold ends in %d day(s)" % int(remaining) + 1
                            if False else
                            "hold ends in ~%d day(s)" % (remaining))

                def do_cancel(i=item_id):
                    queue.cancel(i)
                    ui.notify("Cancelled.")
                    build_active_tab()

                ui.button("Cancel", on_click=do_cancel).props(
                    "outline color=grey")

        ui.label("READY TO REMOVE").classes("text-sm font-bold").style(
            "margin-top:16px;color:#999;")
        if not due:
            ui.label("Nothing is ready to remove.")
        for item_id, record in due:
            with ui.row().classes(
                    "w-full items-center").style(_card_style()):
                with ui.column().style("flex:1;"):
                    ui.label("%s   %.1f GB" % (record["title"],
                                              record["size_bytes"] / 1e9))
                    ui.label("hold elapsed").style("color:#999;font-size:12px;")

                def do_cancel(i=item_id):
                    queue.cancel(i)
                    ui.notify("Cancelled.")
                    build_active_tab()

                ui.button("Cancel", on_click=do_cancel).props(
                    "outline color=grey")

        if due:
            scan_age = STORE.scan_age_days()
            max_scan_age = cfg.get("max_scan_age_days", 3)
            with ui.row().classes(
                    "w-full items-center").style(_card_style()):
                total_bytes = sum(r["size_bytes"] for _, r in due)
                ui.label("%d item(s), %.1f GB." % (len(due),
                                                   total_bytes / 1e9))
                if scan_age is not None and scan_age > max_scan_age:
                    ui.label("Scan is stale - re-scan from the Dashboard "
                            "before removing anything.").style(
                        "color:%s;" % AMBER_COLOR)
                else:
                    confirm_input = ui.input(
                        placeholder="Type REMOVE to enable")
                    remove_button = ui.button("Remove %d item(s)"
                                             % len(due))
                    remove_button.props("color=red")
                    remove_button.set_enabled(False)

                    def check_confirm(e):
                        remove_button.set_enabled(
                            confirm_input.value == "REMOVE")

                    confirm_input.on_value_change(check_confirm)

                    def do_execute():
                        import reclaim
                        try:
                            result = reclaim.execute(
                                STORE.lib, STORE.movie_lib, queue,
                                [i for i, _ in due], cfg)
                            ui.notify("Removed %d item(s)."
                                     % len(result["removed"]))
                        except reclaim.ReclaimError as exc:
                            ui.notify("Run aborted: %s" % exc, type="negative")
                        build_active_tab()

                    remove_button.on_click(do_execute)


def reclaim_defaults_hold_days():
    import reclaim
    return reclaim.DEFAULT_HOLD_DAYS


def _build_history(container):
    with container:
        ui.label("History").classes("text-xl font-bold")
        ui.label("Append-only record of every executed removal. "
                "Read-only.").style("color:#999;")
        history = STORE.history()
        if not history:
            ui.label("Nothing has been removed yet.")
            return
        for record in sorted(history, key=lambda r: -r.get("removed_at", 0)):
            when = datetime.datetime.fromtimestamp(
                record.get("removed_at", 0)).strftime("%Y-%m-%d %H:%M")
            with ui.column().style(_card_style()).classes("w-full"):
                ui.label("%s   %.1f GB   removed %s"
                        % (record["title"], record["size_bytes"] / 1e9,
                           when))


BUILDERS = {
    "dashboard": _build_dashboard,
    "tv": _build_tv,
    "movies": _build_movies,
    "blocked": _build_blocked,
    "hold": _build_hold,
    "history": _build_history,
}

_active_container = {"container": None, "key": None}


def build_active_tab():
    key = _active_container["key"]
    container = _active_container["container"]
    if container is None or key is None:
        return
    container.clear()
    BUILDERS[key](container)


@ui.page("/")
def index():
    ui.dark_mode().enable()

    with ui.row().classes("w-full no-wrap").style("gap:0;align-items:stretch;"):
        with ui.column().style(
                "width:220px;background:#161616;padding:16px 0;"
                "min-height:100vh;gap:4px;"):
            ui.label("BROOMARR").classes("text-lg font-bold").style(
                "padding:0 16px;")
            age_days = STORE.scan_age_days()
            ui.label(data.format_age(age_days)).style(
                "padding:0 16px;color:#999;font-size:12px;")

            main_area = {"container": None}

            def switch(key):
                _active_container["key"] = key
                build_active_tab()

            for group_label, keys in NAV_GROUPS:
                border = ("border-top:2px solid %s;" % AMBER_COLOR
                          if group_label == "RECLAIM" else "")
                ui.label(group_label).style(
                    "padding:12px 16px 4px;color:#777;font-size:11px;"
                    "font-weight:600;letter-spacing:.08em;" + border)
                for key in keys:
                    label = TAB_LABELS[key]
                    if key == "hold":
                        pending_count = sum(
                            1 for r in STORE.queue().items.values()
                            if r["state"] == "PENDING")
                        if pending_count:
                            label += " (%d)" % pending_count
                    ui.button(label, on_click=lambda _, k=key: switch(k)
                             ).props("flat align=left").style(
                        "width:100%;justify-content:flex-start;")

        with ui.column().classes("w-full").style("padding:16px;") as content:
            _active_container["container"] = content

    switch("dashboard")


def run():
    ui.run(title="Broomarr", host="localhost", port=config.PORT,
          reload=False, favicon="\U0001F9F9", dark=True,
          show=False)


if __name__ in {"__main__", "__mp_main__"}:
    run()
