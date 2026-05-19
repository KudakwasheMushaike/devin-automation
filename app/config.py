"""
config.py — Central place for all environment variables.

Every secret and configurable value lives here.
The rest of the app imports from this file — nothing else
reads os.environ directly. This makes it easy to see at a
glance what the app needs to run.
"""

import os

# ── Devin ────────────────────────────────────────────────────────────────────
# Your Devin API key — get this from app.devin.ai → Settings → API Keys
# We use the v1 API which accepts a personal API key directly.
DEVIN_API_KEY = os.environ.get("DEVIN_API_KEY", "")

# Base URL for the Devin v1 API
DEVIN_API_BASE = "https://api.devin.ai/v1"

# ── GitHub ────────────────────────────────────────────────────────────────────
# A GitHub Personal Access Token with repo scope.
# Used to post comments back on issues after Devin opens a PR.
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# The webhook secret you set in GitHub → Settings → Webhooks.
# Used to verify that incoming webhook payloads are really from GitHub
# and not from someone trying to spoof requests to your server.
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")

# Your fork — used when posting comments back to issues.
GITHUB_REPO = os.environ.get("GITHUB_REPO", "KudakwasheMushaike/superset-devin-demo")

# ── App ───────────────────────────────────────────────────────────────────────
# The label that marks an issue as a Devin task.
# Only issues with this label will trigger automation.
DEVIN_TRIGGER_LABEL = os.environ.get("DEVIN_TRIGGER_LABEL", "devin-task")

# How often (in seconds) the background poller checks Devin session status.
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))

# Path to the SQLite database file used for observability.
DATABASE_PATH = os.environ.get("DATABASE_PATH", "/app/data/tasks.db")
