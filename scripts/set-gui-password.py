#!/usr/bin/env python3
"""Print a password hash to paste into config/config.json's gui_users.

Usage:
    python scripts/set-gui-password.py [--role admin|viewer]

Prompts for a password with getpass (never echoed, never logged) and
prints the resulting hash string plus a ready-to-paste gui_users snippet.
This script only ever prints; it never writes config.json itself, since
gui_users also needs a username key chosen by hand and this keeps the
one file with real secrets under the caller's own control.
"""
import argparse
import getpass
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gui import auth  # noqa: E402  (sys.path must be set up first)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--role", choices=("admin", "viewer"), default="admin",
        help="role for the snippet below the hash (default: admin)")
    parser.add_argument(
        "--username", default="USERNAME",
        help="username for the snippet below the hash (default: a "
             "placeholder to edit by hand)")
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match - nothing printed.", file=sys.stderr)
        return 1
    if not password:
        print("Password was empty - nothing printed.", file=sys.stderr)
        return 1

    password_hash = auth.hash_password(password)
    print()
    print("Add this under gui_users in config/config.json:")
    print()
    print('  "%s": {' % args.username)
    print('    "password_hash": "%s",' % password_hash)
    print('    "role": "%s"' % args.role)
    print("  }")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
