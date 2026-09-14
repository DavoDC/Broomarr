"""Session-cookie auth gate for the GUI.

Off by default: if config.json has no `gui_users`, nothing here is wired
in and the GUI behaves exactly as it always has (localhost only, no
login). Only once at least one account is configured does the login page
and the middleware below start refusing requests. See docs/IDEAS.md
"Tailscale access for a friend, prerequisites before giving it out" for
the full reasoning.

hash_password()/verify_password() are stdlib-only (hashlib.pbkdf2_hmac +
hmac.compare_digest) - no new dependency, per the same file. current_user()
reads app.storage.user, which NiceGUI backs with a server-side session
keyed by the cookie set once `ui.run(storage_secret=...)` is configured -
see gui/main.py's run(). RequireLoginMiddleware is a Starlette
BaseHTTPMiddleware that redirects every other request to /login,
allowlisting only /login itself and NiceGUI's own internal routes (static
assets, the websocket upgrade, component/library/resource endpoints),
which all live under one prefix, /_nicegui.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse

from nicegui import app, ui

# Import gui.config first (not just gui/main.py, which happens to do
# this already) so this module's own `import broomarr` below works
# regardless of which module a caller imports first - see the "gui/data.py
# only imports successfully by luck" finding in docs/IDEAS.md.
from gui import config as _gui_config  # noqa: F401  (sys.path side effect)
import broomarr

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 260_000
_SALT_BYTES = 16

# A short, fixed delay after any failed login attempt - not a growing
# lockout, just enough friction that a script cannot spin through a
# password list at network speed. Applied the same way on every failure
# regardless of cause, which is also why it never distinguishes an
# unknown username from a wrong password.
FAILED_LOGIN_DELAY_SECONDS = 1.5

# NiceGUI's own internal routes - two separate mounts, not one shared
# prefix: static/component/library/resource assets live under
# "/_nicegui/{version}/...", and the socket.io app (its polling
# handshake and, later, the websocket upgrade) is mounted at
# "/_nicegui_ws/...". Gating the socket.io polling handshake would break
# every page for every logged-in user too, not just an unauthenticated
# one - NiceGUI's whole reactivity depends on that connection succeeding.
_NICEGUI_INTERNAL_PREFIXES = ("/_nicegui/", "/_nicegui_ws/")


def hash_password(password):
    """Return a self-contained hash string - algorithm, iteration count,
    salt and derived key, all hex-encoded and dollar-separated - so a
    later verify never has to guess what produced it or assume today's
    iteration count.
    """
    salt = os.urandom(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return "%s$%d$%s$%s" % (
        _ALGORITHM, _ITERATIONS, salt.hex(), derived.hex())


def verify_password(password, stored_hash):
    """Constant-time comparison against a hash produced by hash_password().
    Returns False - never raises - for a malformed or empty stored hash,
    so a blank/corrupt config entry fails closed instead of crashing the
    login page.
    """
    try:
        algorithm, iterations, salt_hex, expected_hex = stored_hash.split("$")
        if algorithm != _ALGORITHM:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
        iterations = int(iterations)
    except (ValueError, AttributeError, TypeError):
        return False
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(derived, expected)


def _load_cfg():
    """A fresh read of config.json for every auth decision, so editing
    gui_users or rotating a password takes effect without restarting the
    GUI process. Cheap - it is one small JSON file, and this is never on
    a hot path (login attempts and page-nav checks only).
    """
    try:
        return broomarr.load_config()
    except SystemExit:
        return {}


def is_enabled(cfg=None):
    """Auth is entirely off when gui_users is empty or unset, so an
    existing localhost-only install with no config changes keeps working
    unchanged.
    """
    if cfg is None:
        cfg = _load_cfg()
    return bool(cfg.get("gui_users"))


def check_credentials(name, password):
    """Return the matching account's role ("admin"/"viewer") if name and
    password are both correct, else None - one outcome for "no such
    user", "wrong password" and "malformed hash", by construction, since
    the login page must show one generic message regardless of which it
    was.
    """
    cfg = _load_cfg()
    users = cfg.get("gui_users") or {}
    account = users.get(name) or {}
    if not verify_password(password, account.get("password_hash", "")):
        return None
    return account.get("role")


def current_user():
    """The logged-in user's {"name": ..., "role": ...}, or None. Reads
    app.storage.user, which is the only source of identity this module
    ever trusts - nothing here reads a header, a query string or a cookie
    directly.
    """
    try:
        storage = app.storage.user
    except RuntimeError:
        # No storage_secret configured, or called outside a request/UI
        # context - either way there is no session to read.
        return None
    name = storage.get("auth_name")
    role = storage.get("auth_role")
    if name is None or role is None:
        return None
    return {"name": name, "role": role}


def log_in(name, role):
    app.storage.user.update({"auth_name": name, "auth_role": role})


def log_out():
    app.storage.user.clear()


def is_admin():
    """Whether the current session may perform a mutating action.

    True when auth is off entirely - a single-user localhost install with
    no gui_users configured behaves exactly as it always did, with no
    role distinction, since nobody ever logged in to have a role. Once
    gui_users is non-empty, only a logged-in "admin" account qualifies.
    """
    if not is_enabled():
        return True
    user = current_user()
    return user is not None and user["role"] == "admin"


def require_admin():
    """Raise PermissionError unless the current session is an admin. Call
    this at the top of every mutating handler (on_flag(), do_cancel(),
    do_execute()) - the role check belongs inside the handler itself, not
    only in which buttons a viewer's page happens to render, since a
    hidden control is not the same thing as a refused action.
    """
    if not is_admin():
        raise PermissionError(
            "this account does not have permission to do that")


def username_for_record():
    """The name to attribute a mutating action to, for state/reclaim-
    history.json. "local" when auth is off (there is no account to name);
    the logged-in account's name otherwise. Never None, so a history
    record always carries a value.
    """
    if not is_enabled():
        return "local"
    user = current_user()
    return user["name"] if user is not None else "unknown"


def _is_nicegui_internal(path):
    return any(path.startswith(prefix) for prefix in _NICEGUI_INTERNAL_PREFIXES)


class RequireLoginMiddleware(BaseHTTPMiddleware):
    """Redirects every request without a valid session to /login, except
    /login itself and NiceGUI's own internal routes. Register this with
    app.add_middleware() BEFORE calling ui.run() - see gui/main.py's
    run() - so NiceGUI's own SessionMiddleware and request-tracking
    middleware end up outermost and have already prepared the session by
    the time this one runs; adding it after ui.run() has started would
    invert that order and make app.storage.user unavailable here.
    """

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path == "/login" or _is_nicegui_internal(path):
            return await call_next(request)
        if current_user() is None:
            return RedirectResponse("/login")
        return await call_next(request)


@ui.page("/login")
def login_page():
    if current_user() is not None:
        ui.navigate.to("/")
        return

    with ui.column().style(
            "max-width:320px;margin:80px auto;gap:8px;"):
        ui.label("Broomarr").classes("text-xl font-bold")
        name_input = ui.input("Username").props("autofocus")
        password_input = ui.input(
            "Password", password=True, password_toggle_button=True)
        message = ui.label("").style("color:#e53935;min-height:20px;")

        async def do_login():
            role = check_credentials(
                name_input.value or "", password_input.value or "")
            if role is None:
                # Non-blocking - a blocking time.sleep() here would freeze
                # the event loop for every connected client, the same
                # mistake flagged elsewhere in the GUI's long-running
                # handlers.
                await asyncio.sleep(FAILED_LOGIN_DELAY_SECONDS)
                message.text = "Incorrect username or password."
                return
            log_in(name_input.value, role)
            ui.navigate.to("/")

        password_input.on("keydown.enter", do_login)
        ui.button("Log in", on_click=do_login)
