"""gui/auth.py - the session-cookie auth gate.

This is the first test file gui/ has ever had (gui/ previously had zero
test infrastructure - see the final report for this repo's auth work for
that finding). Kept to the parts of gui/auth.py that do not require a
live NiceGUI request/UI context: hash_password/verify_password are pure
stdlib functions, and is_enabled/check_credentials/is_admin/
username_for_record/_is_nicegui_internal only need config.json's
contents, which conftest.py's sys.path setup lets this file reach via
"import broomarr" the same way tests/test_reclaim.py does. current_user()
itself needs app.storage.user, which only exists inside a request NiceGUI
is handling - RuntimeError outside that context, which is exactly what
current_user() is documented to treat as "nobody is logged in", so that
behaviour is covered directly without faking a request.
"""
import pytest

from gui import auth


def test_hash_then_verify_round_trips():
    stored = auth.hash_password("correct horse battery staple")
    assert auth.verify_password("correct horse battery staple", stored)


def test_verify_rejects_wrong_password():
    stored = auth.hash_password("correct horse battery staple")
    assert not auth.verify_password("wrong password", stored)


def test_hash_is_salted_so_two_hashes_of_the_same_password_differ():
    first = auth.hash_password("same password")
    second = auth.hash_password("same password")
    assert first != second
    assert auth.verify_password("same password", first)
    assert auth.verify_password("same password", second)


@pytest.mark.parametrize("bad_hash", [
    "",
    "not-even-close-to-the-right-shape",
    "pbkdf2_sha256$not-an-int$aa$bb",
    "pbkdf2_sha256$1000$not-hex$bb",
    "wrong_algorithm$1000$aa$bb",
    None,
])
def test_verify_fails_closed_on_a_malformed_stored_hash(bad_hash):
    assert not auth.verify_password("anything", bad_hash)


def test_is_enabled_false_when_gui_users_absent():
    assert auth.is_enabled({}) is False


def test_is_enabled_false_when_gui_users_empty():
    assert auth.is_enabled({"gui_users": {}}) is False


def test_is_enabled_true_when_gui_users_configured():
    assert auth.is_enabled({"gui_users": {"alice": {}}}) is True


def _cfg_with_users():
    return {
        "gui_users": {
            "admin_user": {
                "password_hash": auth.hash_password("adminpw"),
                "role": "admin",
            },
            "viewer_user": {
                "password_hash": auth.hash_password("viewerpw"),
                "role": "viewer",
            },
        }
    }


def test_check_credentials_returns_role_on_success(monkeypatch):
    cfg = _cfg_with_users()
    monkeypatch.setattr(auth, "_load_cfg", lambda: cfg)
    assert auth.check_credentials("admin_user", "adminpw") == "admin"
    assert auth.check_credentials("viewer_user", "viewerpw") == "viewer"


def test_check_credentials_returns_none_on_wrong_password(monkeypatch):
    cfg = _cfg_with_users()
    monkeypatch.setattr(auth, "_load_cfg", lambda: cfg)
    assert auth.check_credentials("admin_user", "wrong") is None


def test_check_credentials_returns_none_on_unknown_username(monkeypatch):
    cfg = _cfg_with_users()
    monkeypatch.setattr(auth, "_load_cfg", lambda: cfg)
    assert auth.check_credentials("nobody", "adminpw") is None


def test_current_user_is_none_outside_a_nicegui_request_context():
    # No storage_secret is configured and nothing here is inside a
    # NiceGUI page handler, so app.storage.user raises RuntimeError -
    # current_user() must treat that as "not logged in", not propagate it.
    assert auth.current_user() is None


def test_is_admin_true_when_auth_disabled(monkeypatch):
    # A single-user localhost install with no gui_users configured must
    # keep behaving exactly as it always did - nobody is ever "logged
    # in", so is_admin() has to short-circuit to True rather than treat
    # the absence of a session as "not an admin".
    monkeypatch.setattr(auth, "is_enabled", lambda: False)
    assert auth.is_admin() is True


def test_require_admin_does_not_raise_when_auth_disabled(monkeypatch):
    monkeypatch.setattr(auth, "is_enabled", lambda: False)
    auth.require_admin()  # must not raise


def test_is_admin_false_with_no_session_when_auth_enabled(monkeypatch):
    monkeypatch.setattr(auth, "is_enabled", lambda: True)
    monkeypatch.setattr(auth, "current_user", lambda: None)
    assert auth.is_admin() is False


def test_is_admin_false_for_a_viewer_session_when_auth_enabled(monkeypatch):
    monkeypatch.setattr(auth, "is_enabled", lambda: True)
    monkeypatch.setattr(
        auth, "current_user", lambda: {"name": "v", "role": "viewer"})
    assert auth.is_admin() is False


def test_is_admin_true_for_an_admin_session_when_auth_enabled(monkeypatch):
    monkeypatch.setattr(auth, "is_enabled", lambda: True)
    monkeypatch.setattr(
        auth, "current_user", lambda: {"name": "a", "role": "admin"})
    assert auth.is_admin() is True


def test_require_admin_raises_permission_error_for_a_viewer(monkeypatch):
    monkeypatch.setattr(auth, "is_enabled", lambda: True)
    monkeypatch.setattr(
        auth, "current_user", lambda: {"name": "v", "role": "viewer"})
    with pytest.raises(PermissionError):
        auth.require_admin()


def test_username_for_record_is_local_when_auth_disabled(monkeypatch):
    monkeypatch.setattr(auth, "is_enabled", lambda: False)
    assert auth.username_for_record() == "local"


def test_username_for_record_is_the_logged_in_name_when_enabled(monkeypatch):
    monkeypatch.setattr(auth, "is_enabled", lambda: True)
    monkeypatch.setattr(
        auth, "current_user", lambda: {"name": "someone", "role": "admin"})
    assert auth.username_for_record() == "someone"


@pytest.mark.parametrize("path", [
    "/_nicegui/1.2.3/static/x.js",
    "/_nicegui/1.2.3/libraries/vue.js",
    "/_nicegui_ws/socket.io/",
    "/_nicegui_ws/socket.io/?EIO=4",
])
def test_nicegui_internal_paths_are_recognised(path):
    assert auth._is_nicegui_internal(path)


@pytest.mark.parametrize("path", [
    "/",
    "/login",
    "/hold",
    "/_nicegui-lookalike-but-not-actually-internal",
])
def test_non_nicegui_paths_are_not_recognised_as_internal(path):
    assert not auth._is_nicegui_internal(path)
