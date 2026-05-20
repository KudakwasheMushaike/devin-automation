# Devin Automation Server

Event-driven automation that connects GitHub issues to Devin sessions. When a GitHub issue is labeled with `devin-task`, this FastAPI service creates a Devin session, tracks progress in SQLite, comments status updates back on GitHub, and exposes a small observability dashboard.

## What It Does

- Receives GitHub webhooks at `POST /webhook/github`
- Verifies GitHub webhook signatures when `GITHUB_WEBHOOK_SECRET` is set
- Starts a Devin session for issues labeled with `devin-task`
- Posts a GitHub comment when Devin starts working
- Polls Devin until the session completes, fails, or times out
- Detects Devin-created pull requests from GitHub PR webhooks
- Stores task history in SQLite
- Serves a dashboard at `/` and JSON APIs under `/api`

## Architecture

```text
GitHub issue labeled "devin-task"
        |
        v
POST /webhook/github
        |
        v
Create Devin session
        |
        v
Store task in SQLite and comment on GitHub
        |
        v
Poll Devin session status
        |
        v
Devin opens PR -> GitHub PR webhook marks task complete
```

## Requirements

- Docker and Docker Compose, or Python 3.11+
- Devin API key
- GitHub personal access token with permission to comment on issues
- GitHub webhook configured for issue and pull request events

## Configuration

Create a `.env` file from the example:

```bash
cp .env.example .env
```

Set these values:

```env
DEVIN_API_KEY=your_devin_api_key
GITHUB_TOKEN=your_github_token
GITHUB_WEBHOOK_SECRET=your_webhook_secret
GITHUB_REPO=KudakwasheMushaike/superset-devin-demo
```

Optional environment variables:

```env
DEVIN_TRIGGER_LABEL=devin-task
POLL_INTERVAL_SECONDS=60
DATABASE_PATH=/app/data/tasks.db
```

## Run With Docker

```bash
docker compose up --build
```

The app will be available at:

```text
http://localhost:8000
```

SQLite data is persisted in `./data/tasks.db`.

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

For local runs outside Docker, set `DATABASE_PATH` to a writable local path if needed:

```env
DATABASE_PATH=./data/tasks.db
```

## GitHub Webhook Setup

In the target GitHub repository, add a webhook:

- Payload URL: `https://your-public-url/webhook/github`
- Content type: `application/json`
- Secret: same value as `GITHUB_WEBHOOK_SECRET`
- Events: `Issues` and `Pull requests`

For local development, expose the server with a tunnel such as ngrok and use the generated HTTPS URL as the webhook base URL.

## Usage

1. Start the server.
2. Add the `devin-task` label to a GitHub issue.
3. The service creates a Devin session and comments on the issue.
4. Devin works on the issue and opens a pull request.
5. The PR webhook marks the task complete and posts a completion comment.
6. Track progress in the dashboard at `/`.

## API Endpoints

- `GET /` - Observability dashboard
- `GET /health` - Health check
- `GET /api/tasks` - All tracked tasks
- `GET /api/stats` - Summary task statistics
- `POST /webhook/github` - GitHub webhook receiver

## Project Structure

```text
app/
  main.py           FastAPI app, webhook handler, polling loop
  database.py       SQLite setup and task persistence helpers
  devin_client.py   Devin API wrapper
  github_client.py  GitHub webhook verification and comments
  config.py         Environment variable configuration
  dashboard.html    Observability UI
data/
  tasks.db          Local SQLite task history
Dockerfile
docker-compose.yml
requirements.txt
```

## Notes

- If `GITHUB_WEBHOOK_SECRET` is empty, signature verification is skipped. This is useful for local development but should not be used in production.
- The default trigger label is `devin-task`.
- The Docker setup persists task history by mounting `./data` into the container.
