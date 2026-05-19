"""
devin_client.py — Thin wrapper around the Devin v1 REST API.

Keeps all Devin API logic in one place.
The rest of the app never touches requests or URLs directly —
it just calls these functions. If the Devin API changes,
we only update this file.
"""

import requests
from .config import DEVIN_API_KEY, DEVIN_API_BASE


def _headers() -> dict:
    """
    Builds the auth headers required by every Devin API call.
    The API key goes in the Authorization header as a Bearer token.
    """
    return {
        "Authorization": f"Bearer {DEVIN_API_KEY}",
        "Content-Type": "application/json"
    }


def create_session(prompt: str, issue_number: int) -> dict:
    """
    Creates a new Devin session with the given prompt.

    The prompt is the most important thing here — it's what Devin
    reads to understand the task. We pass it in from main.py where
    we build it from the GitHub issue details.

    Returns the full session object from Devin, which includes:
    - session_id: unique ID we use to poll for status
    - url: link to the session in the Devin UI
    - status: initially 'new'

    We also tag the session with the issue number so we can
    identify it later in the Devin UI and in audit logs.
    """
    response = requests.post(
        f"{DEVIN_API_BASE}/sessions",
        headers=_headers(),
        json={
            "prompt": prompt,
            # Tags appear in the Devin UI — useful for filtering sessions
            # by project or issue number.
            "tags": [f"issue-{issue_number}", "superset-devin-demo", "cve-remediation"]
        },
        timeout=30
    )
    response.raise_for_status()
    return response.json()


def get_session(session_id: str) -> dict:
    """
    Fetches the current state of a Devin session.

    Called repeatedly by the polling loop in main.py until
    the session reaches a terminal state (completed or failed).

    The response includes:
    - status: 'new' | 'running' | 'completed' | 'failed' | 'stopped'
    - pull_requests: list of PRs Devin opened (populated on completion)
    - status_detail: human readable detail e.g. 'working', 'waiting'
    """
    response = requests.get(
        f"{DEVIN_API_BASE}/session/{session_id}",
        headers=_headers(),
        timeout=30
    )
    response.raise_for_status()
    return response.json()


def send_message(session_id: str, message: str) -> dict:
    """
    Sends a follow-up message to an active Devin session.

    Not used in the main happy path, but useful if you want to
    give Devin additional context mid-session, e.g.:
    "Also make sure to update the changelog."

    Could be extended to let engineers interact with Devin
    via GitHub comments — a natural next step for this system.
    """
    response = requests.post(
        f"{DEVIN_API_BASE}/session/{session_id}/message",
        headers=_headers(),
        json={"message": message},
        timeout=30
    )
    response.raise_for_status()
    return response.json()


def extract_pr_url(session: dict) -> str | None:
    """
    Safely extracts the first PR URL from a completed session.

    The Devin API returns pull_requests as a list of objects,
    each with pr_url and pr_state. We grab the first open one.
    Returns None if no PR was opened yet.
    """
    prs = session.get("pull_requests", [])
    if not prs:
        return None
    # Prefer open PRs, fall back to any PR
    for pr in prs:
        if pr.get("pr_state") == "open":
            return pr.get("pr_url")
    return prs[0].get("pr_url")
