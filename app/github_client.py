"""
github_client.py — Thin wrapper around the GitHub REST API.

Two responsibilities:
1. Verify that incoming webhook payloads are genuinely from GitHub
2. Post comments back on issues so engineers can see Devin's progress
   directly in GitHub — without needing to open the Devin UI.
"""

import hashlib
import hmac
import requests
from .config import GITHUB_TOKEN, GITHUB_WEBHOOK_SECRET, GITHUB_REPO


def verify_webhook_signature(payload_bytes: bytes, signature_header: str) -> bool:
    """
    Verifies that a webhook payload was sent by GitHub and not spoofed.

    How it works:
    - GitHub signs every webhook payload using your webhook secret
      with HMAC-SHA256 and sends the signature in the X-Hub-Signature-256 header
    - We compute the same HMAC using our copy of the secret
    - If the signatures match, the payload is authentic

    We use hmac.compare_digest instead of == to prevent timing attacks —
    a subtle security detail that matters in production.
    """
    if not GITHUB_WEBHOOK_SECRET:
        # If no secret is configured, skip verification.
        # Fine for local dev, not for production.
        return True

    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)


def post_issue_comment(issue_number: int, body: str):
    """
    Posts a comment on a GitHub issue.

    We call this at two points:
    1. When Devin starts — "🤖 Devin is working on this..."
    2. When Devin finishes — "✅ PR opened: <link>" or "❌ Failed: <reason>"

    This makes the automation visible to engineers in their normal
    GitHub workflow — they don't need to check a separate dashboard.
    """
    url = f"https://api.github.com/repos/{GITHUB_REPO}/issues/{issue_number}/comments"
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        },
        json={"body": body},
        timeout=30
    )
    response.raise_for_status()
    return response.json()


def build_started_comment(session_id: str, session_url: str) -> str:
    """
    Builds the comment posted when Devin starts a session.
    Gives engineers visibility without them needing to check anything.
    """
    return f"""🤖 **Devin has started working on this issue.**

| Field | Value |
|-------|-------|
| Session ID | `{session_id}` |
| Devin Session | [View in Devin]({session_url}) |
| Status | 🔄 Running |

Devin will open a pull request when complete. This comment will be followed by a status update.
"""


def build_completed_comment(pr_url: str, session_url: str) -> str:
    """
    Builds the comment posted when Devin successfully opens a PR.
    """
    return f"""✅ **Devin has completed this task.**

| Field | Value |
|-------|-------|
| Pull Request | [View PR]({pr_url}) |
| Devin Session | [View Session]({session_url}) |
| Status | ✅ Completed |

Please review the pull request and merge when ready.
"""


def build_failed_comment(error: str, session_url: str) -> str:
    """
    Builds the comment posted when Devin fails.
    Honest failure reporting is part of good observability.
    """
    return f"""❌ **Devin was unable to complete this task.**

| Field | Value |
|-------|-------|
| Error | `{error}` |
| Devin Session | [View Session]({session_url}) |
| Status | ❌ Failed |

You may want to review the session and retry with a more specific prompt.
"""
