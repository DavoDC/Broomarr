#!/usr/bin/env python3
"""Acceptance check: with gui_users configured, no route serves app content
to an unauthenticated caller.

Run this against a GUI that is already up (python -m gui.main, or
scripts/run-gui.bat) and whose config.json has gui_users set:

    python scripts/check-auth-enforced.py [base_url]

base_url defaults to http://127.0.0.1:8472, matching the GUI's own
default gui_host/gui_port.

What it checks, and why "every route" does not mean one blanket rule:
  - "/" must never return the app shell to a caller with no session -
    either a redirect to /login, or a 401/403, but never the page itself.
  - "/login" must be reachable (status 200) with no session, since that
    is the one page an unauthenticated caller has to reach.
  - NiceGUI's own internal routes (static assets, the socket.io
    handshake) are allowlisted by gui/auth.py's RequireLoginMiddleware
    on purpose - gating the socket.io connection itself would break the
    page for logged-in users too, since NiceGUI's reactivity depends on
    it. This script does not assert those are blocked; it instead
    confirms they never hand back the authenticated app shell (the same
    APP_SHELL_MARKER check as "/"), which is the actual security
    property that matters for a static-asset endpoint.

Exits 0 if every check passes, 1 otherwise, printing a PASS/FAIL line per
route checked.
"""
import sys
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8472"

# Text that only ever appears once a session is authenticated and the app
# shell has rendered - see gui/main.py's index(), which prints this in
# the sidebar. Its presence in a response body means real app content
# leaked to an unauthenticated caller.
APP_SHELL_MARKER = "BROOMARR"

# NiceGUI's two internal mounts - see gui/auth.py's
# _NICEGUI_INTERNAL_PREFIXES for why these are two separate prefixes
# rather than one.
NICEGUI_PROBE_PATHS = ("/_nicegui/1/libraries/index.html",
                       "/_nicegui_ws/socket.io/")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Report the raw 3xx status instead of silently following it, so a
    redirect-to-/login is visible to this script rather than hidden
    behind an automatic second request.
    """

    def redirect_request(self, *args, **kwargs):
        return None


def _fetch(base_url, path):
    opener = urllib.request.build_opener(_NoRedirectHandler)
    url = base_url.rstrip("/") + path
    try:
        with opener.open(url, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        print("Could not reach %s: %s" % (url, exc), file=sys.stderr)
        print("Is the GUI running, and gui_users configured?",
              file=sys.stderr)
        sys.exit(2)


def main():
    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL
    failures = []

    status, body = _fetch(base_url, "/")
    ok = (300 <= status < 400) or status in (401, 403)
    ok = ok and APP_SHELL_MARKER not in body
    print("%s  GET /  -> %s" % ("PASS" if ok else "FAIL", status))
    if not ok:
        failures.append("/")

    status, body = _fetch(base_url, "/login")
    ok = status == 200
    print("%s  GET /login  -> %s" % ("PASS" if ok else "FAIL", status))
    if not ok:
        failures.append("/login")

    for path in NICEGUI_PROBE_PATHS:
        status, body = _fetch(base_url, path)
        # Allowlisted by design (see module docstring) - only assert the
        # authenticated app shell never leaks through this path.
        ok = APP_SHELL_MARKER not in body
        print("%s  GET %s  -> %s (allowlisted internal route, checked "
             "for app-shell leakage only)" % ("PASS" if ok else "FAIL",
                                              path, status))
        if not ok:
            failures.append(path)

    if failures:
        print("\nFAILED: %s" % ", ".join(failures))
        return 1
    print("\nAll routes correctly refuse an unauthenticated caller.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
