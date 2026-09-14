"""Paths and constants shared across the GUI. No safety logic here - only
where things live on disk.
"""
import os
import sys

GUI_ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(GUI_ROOT)
SRC_DIR = os.path.join(REPO_ROOT, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

STATE_DIR = os.path.join(REPO_ROOT, "state")
LAST_SCAN_PATH = os.path.join(STATE_DIR, "last-scan.json")
QUEUE_PATH = os.path.join(STATE_DIR, "reclaim-queue.json")
HISTORY_PATH = os.path.join(STATE_DIR, "reclaim-history.json")
COVERS_CACHE_DIR = os.path.join(GUI_ROOT, ".cache", "covers")

# Defaults for the two config.json keys below - a bare-loopback listener
# on the same port the GUI has always used, so an existing install with
# no config changes keeps working unchanged. 0.0.0.0 must never be one of
# these values, in config or here: that would publish the app to the
# whole home LAN, a strictly larger audience than the tailnet reverse
# proxy this is meant for - see docs/IDEAS.md "Tailscale access for a
# friend, prerequisites before giving it out".
DEFAULT_GUI_HOST = "127.0.0.1"
DEFAULT_GUI_PORT = 8472


def gui_host(cfg):
    return cfg.get("gui_host") or DEFAULT_GUI_HOST


def gui_port(cfg):
    return cfg.get("gui_port") or DEFAULT_GUI_PORT
