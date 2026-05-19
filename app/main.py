"""
main.py — The heart of the automation.

This FastAPI app does three things:
1. Receives GitHub webhooks when issues are labeled
2. Triggers Devin sessions to fix those issues
3. Serves the observability dashboard and API

Flow:
  GitHub issue labeled "devin-task"
    → POST /webhook/github
      → verify signature
      → build prompt from issue details
      → call Devin API to create session
      → post GitHub comment "Devin is working on this"
      → start background polling loop
        → every 30s: check session status
        → on completion: post GitHub comment with PR link
        → update SQLite database throughout
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse

from . import database
from . import devin_client
from . import github_client
from .config import DEVIN_TRIGGER_LABEL, POLL_INTERVAL_SECONDS

# ── Logging ──────────────────────────────────────────────────────────────────
# Structured logs are your friend when debugging automation at 2am.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


# ── App Lifecycle ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once at startup before the server starts accepting requests.
    We initialise the database here so the tables exist before
    any webhook arrives.
    """
    logger.info("Starting Devin Automation Server...")
    database.init_db()
    logger.info("Database initialised.")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="Devin Automation Server",
    description="Event-driven automation that triggers Devin to remediate GitHub issues.",
    version="1.0.0",
    lifespan=lifespan
)


# ── Prompt Builder ────────────────────────────────────────────────────────────
def build_devin_prompt(issue_number: int, issue_title: str,
                        issue_body: str, issue_url: str) -> str:
    """
    Builds the prompt we send to Devin for each issue.

    This is the most important function in the whole system.
    A well-crafted prompt means Devin succeeds on the first try.

    Key principles from Cognition's own blog:
    - Give Devin the issue URL so it can read the full context itself
    - State the repository explicitly
    - Tell Devin what to do AFTER making changes (open a PR)
    - Keep it concise — Devin is smart enough to infer the rest
    """
    return f"""You have been assigned to fix a GitHub issue in the Apache Superset fork.

Repository: https://github.com/KudakwasheMushaike/superset-devin-demo
Issue #{issue_number}: {issue_title}
Issue URL: {issue_url}

Issue Description:
{issue_body}

Instructions:
1. Read the issue carefully and understand what needs to be fixed
2. Explore the repository to find all relevant files that need to be changed
3. Make the necessary changes to resolve the issue
4. Ensure no existing tests are broken by your changes
5. Open a pull request with a clear description referencing Issue #{issue_number}

Please proceed autonomously and open a pull request when complete.
"""


# ── Webhook Endpoint ──────────────────────────────────────────────────────────
@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    The main entry point — receives GitHub webhook events.

    GitHub sends a POST request to this endpoint whenever
    something happens in your repository. We configured it
    to send 'issues' events.

    We filter down to exactly one event type:
    'labeled' + label name == 'devin-task'

    Everything else is ignored immediately with a 200 OK
    (GitHub expects a fast response or it retries).
    """
    # Step 1: Read the raw body BEFORE parsing JSON
    # We need the raw bytes to verify the HMAC signature.
    payload_bytes = await request.body()

    # Step 2: Verify the webhook came from GitHub
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not github_client.verify_webhook_signature(payload_bytes, signature):
        logger.warning("Webhook signature verification failed — rejecting request")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Step 3: Parse the JSON payload
    payload = await request.json()

    # Step 4: Filter — only act on 'labeled' issue events
    action = payload.get("action")
    if action != "labeled":
        # Not a labeling event — ignore silently
        return {"status": "ignored", "reason": f"action={action}"}

    # Step 5: Filter — only act on our specific trigger label
    label_name = payload.get("label", {}).get("name", "")
    if label_name != DEVIN_TRIGGER_LABEL:
        return {"status": "ignored", "reason": f"label={label_name}"}

    # Step 6: Extract issue details
    issue = payload.get("issue", {})
    issue_number = issue.get("number")
    issue_title = issue.get("title", "")
    issue_body = issue.get("body", "") or ""
    issue_url = issue.get("html_url", "")

    logger.info(f"Trigger received for Issue #{issue_number}: {issue_title}")

    # Step 7: Log the task to our database immediately
    # Status is 'pending' until Devin accepts the session
    task_id = database.log_task(issue_number, issue_title, issue_url)

    # Step 8: Hand off to background task and return immediately
    # GitHub expects a response within 10 seconds.
    # The actual Devin session creation and polling happens in the background.
    background_tasks.add_task(
        process_issue,
        task_id=task_id,
        issue_number=issue_number,
        issue_title=issue_title,
        issue_body=issue_body,
        issue_url=issue_url
    )

    return {
        "status": "accepted",
        "task_id": task_id,
        "issue": issue_number
    }


# ── Background Task ───────────────────────────────────────────────────────────
async def process_issue(task_id: int, issue_number: int, issue_title: str,
                         issue_body: str, issue_url: str):
    """
    Runs in the background after the webhook returns.

    This function:
    1. Builds the Devin prompt
    2. Creates the Devin session
    3. Posts a GitHub comment so engineers know Devin is working
    4. Polls Devin until it completes or fails
    5. Posts a final GitHub comment with the PR link
    6. Updates the database throughout
    """
    session_id = None
    session_url = None

    try:
        # ── Create Devin Session ──────────────────────────────────────────────
        logger.info(f"[Task {task_id}] Creating Devin session for Issue #{issue_number}")

        prompt = build_devin_prompt(issue_number, issue_title, issue_body, issue_url)
        session = devin_client.create_session(prompt, issue_number)

        session_id = session.get("session_id") or session.get("id")
        session_url = session.get("url", f"https://app.devin.ai/sessions/{session_id}")

        logger.info(f"[Task {task_id}] Devin session created: {session_id}")

        # ── Update DB with session info ───────────────────────────────────────
        database.update_task_session(task_id, session_id, session_url)

        # ── Notify GitHub ─────────────────────────────────────────────────────
        # Post a comment on the issue so the team can see Devin is working.
        # This is visible in GitHub without anyone needing to check the dashboard.
        github_client.post_issue_comment(
            issue_number,
            github_client.build_started_comment(session_id, session_url)
        )

        # ── Poll for Completion ───────────────────────────────────────────────
        # Devin sessions are async — we check the status every 30 seconds
        # until the session reaches a terminal state.
        logger.info(f"[Task {task_id}] Polling session {session_id}...")

        max_polls = 60  # 60 × 30s = 30 minutes max before we give up
        polls = 0

        while polls < max_polls:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            polls += 1

            session_status = devin_client.get_session(session_id)
            status = session_status.get("status", "")
            status_detail = session_status.get("status_detail", "")

            logger.info(
                f"[Task {task_id}] Poll {polls}: status={status} detail={status_detail}"
            )

            if status in ("completed", "exit"):
                # ── Success ───────────────────────────────────────────────────
                pr_url = devin_client.extract_pr_url(session_status)

                if pr_url:
                    database.update_task_completed(task_id, pr_url)
                    github_client.post_issue_comment(
                        issue_number,
                        github_client.build_completed_comment(pr_url, session_url)
                    )
                    logger.info(f"[Task {task_id}] ✅ Completed. PR: {pr_url}")
                else:
                    # Session completed but no PR — unusual, treat as failure
                    database.update_task_failed(task_id, "Session completed but no PR found")
                    github_client.post_issue_comment(
                        issue_number,
                        github_client.build_failed_comment(
                            "Session completed but no PR was opened", session_url
                        )
                    )
                    logger.warning(f"[Task {task_id}] Session completed with no PR")
                return

            elif status in ("failed", "stopped", "error", "suspended"):
                # ── Failure ───────────────────────────────────────────────────
                error = status_detail or f"Session ended with status: {status}"
                database.update_task_failed(task_id, error)
                github_client.post_issue_comment(
                    issue_number,
                    github_client.build_failed_comment(error, session_url)
                )
                logger.error(f"[Task {task_id}] ❌ Failed: {error}")
                return

            # Still running — continue polling

        # ── Timeout ───────────────────────────────────────────────────────────
        database.update_task_failed(task_id, "Timed out after 30 minutes")
        github_client.post_issue_comment(
            issue_number,
            github_client.build_failed_comment("Timed out after 30 minutes", session_url)
        )
        logger.error(f"[Task {task_id}] Timed out after {max_polls} polls")

    except Exception as e:
        # ── Unexpected Error ──────────────────────────────────────────────────
        error_msg = str(e)
        logger.exception(f"[Task {task_id}] Unexpected error: {error_msg}")
        database.update_task_failed(task_id, error_msg)

        if issue_number and session_url:
            try:
                github_client.post_issue_comment(
                    issue_number,
                    github_client.build_failed_comment(error_msg, session_url or "N/A")
                )
            except Exception:
                pass  # Don't let a comment failure hide the original error


# ── Observability API ─────────────────────────────────────────────────────────
@app.get("/api/tasks")
def get_tasks():
    """
    Returns all tasks as JSON.
    Polled by the dashboard every 10 seconds to show live status.
    """
    return JSONResponse(content=database.get_all_tasks())


@app.get("/api/stats")
def get_stats():
    """
    Returns summary statistics.
    Displayed in the dashboard header cards.
    """
    return JSONResponse(content=database.get_stats())


@app.get("/health")
def health():
    """
    Simple health check endpoint.
    Used by Docker healthcheck and load balancers.
    """
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def dashboard():
    """
    Serves the observability dashboard.
    Reads the HTML file at startup — no template engine needed.
    """
    try:
        with open("/app/app/dashboard.html", "r") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Dashboard not found</h1>"

