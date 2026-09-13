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

PORT = 8472
