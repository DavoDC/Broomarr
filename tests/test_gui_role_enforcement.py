"""Role enforcement lives inside the mutating handlers themselves, not
only in which buttons a viewer's page happens to render - docs/IDEAS.md
item 4. gui/main.py's on_flag(), both do_cancel() closures in
_build_hold(), and do_execute() each call auth.require_admin() before
doing anything, and gui/data.py's record_removal_actor() only ever
records an id it was actually given.

The mutating handlers themselves are closures defined inside NiceGUI
page-building functions (_build_review_table(), _build_hold()) and reach
for live ui.* elements and a running event loop, so exercising them
end-to-end would need a real NiceGUI client connection - out of scope
for a stdlib/pytest suite with no browser or websocket harness. What is
tested directly, and is the actual security property item 4 asks for:

  1. auth.require_admin() - the single choke point every one of those
     handlers calls first - correctly refuses a viewer/no-session
     caller and allows an admin/disabled-auth one (see
     tests/test_gui_auth.py for the full behavioural coverage of that
     function).
  2. Source inspection confirms each handler actually calls it, as the
     very first thing it does, rather than relying on a control being
     hidden from view - this is the same source-inspection style already
     used by tests/test_no_gui_dependency.py in this repo.
"""
import os

import pytest

from gui import auth

GUI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PY = os.path.join(GUI_ROOT, "gui", "main.py")


def _read_main():
    with open(MAIN_PY, encoding="utf-8") as fh:
        return fh.read()


def _handler_body(source, def_line, max_chars=1500):
    """A fixed-size slice of source starting at one handler's "def" line
    - good enough to find the calls inside its body without a full
    parser, matching how test_no_gui_dependency.py already inspects gui
    source with plain string operations rather than an AST.
    """
    start = source.index(def_line)
    return source[start:start + max_chars]


def test_on_flag_calls_require_admin_first():
    source = _read_main()
    body = _handler_body(source, "def on_flag(kind_, item_):")
    idx_call = body.index("auth.require_admin()")
    idx_mutate = body.index("STORE.flag(")
    assert idx_call < idx_mutate, (
        "on_flag() must call auth.require_admin() before STORE.flag()")


def test_both_do_cancel_closures_call_require_admin_first():
    source = _read_main()
    count = 0
    search_from = 0
    while True:
        idx = source.find("def do_cancel(i=item_id):", search_from)
        if idx == -1:
            break
        count += 1
        body = source[idx:idx + 500]
        idx_call = body.index("auth.require_admin()")
        idx_mutate = body.index("queue.cancel(")
        assert idx_call < idx_mutate, (
            "do_cancel() must call auth.require_admin() before "
            "queue.cancel()")
        search_from = idx + 1
    assert count == 2, (
        "expected two do_cancel() closures in _build_hold() (ON HOLD and "
        "READY TO REMOVE) - found %d; if this is intentional, update this "
        "test's expected count" % count)


def test_do_execute_calls_require_admin_first():
    source = _read_main()
    idx = source.index("async def do_execute():")
    body = source[idx:idx + 3000]
    idx_call = body.index("auth.require_admin()")
    idx_mutate = body.index("reclaim.execute")
    assert idx_call < idx_mutate, (
        "do_execute() must call auth.require_admin() before "
        "reclaim.execute()")


def test_do_execute_records_the_acting_username():
    source = _read_main()
    idx = source.index("async def do_execute():")
    body = source[idx:idx + 3000]
    assert "auth.username_for_record()" in body
    assert "record_removal_actor" in body


# --- Behavioural coverage of the actual choke point every handler above
# calls first (see module docstring for why the handlers themselves are
# not exercised directly).

def test_require_admin_refuses_a_viewer_the_way_every_handler_relies_on(
        monkeypatch):
    monkeypatch.setattr(auth, "is_enabled", lambda: True)
    monkeypatch.setattr(
        auth, "current_user", lambda: {"name": "v", "role": "viewer"})
    with pytest.raises(PermissionError):
        auth.require_admin()


def test_require_admin_allows_an_admin_the_way_every_handler_relies_on(
        monkeypatch):
    monkeypatch.setattr(auth, "is_enabled", lambda: True)
    monkeypatch.setattr(
        auth, "current_user", lambda: {"name": "a", "role": "admin"})
    auth.require_admin()  # must not raise
