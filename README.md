# AOSSIE Discord Agent MVP

A passive Discord listener for AOSSIE contributor questions. It watches only an allowlisted channel, creates one thread per question, routes the question to a repository, retrieves repository Markdown, and replies with source links. It never needs Administrator permission and starts in read-only/audit mode.

## Local setup

```bash
cd discord-agent
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env  # Windows
# cp .env.example .env  # macOS/Linux
```

Put your Discord bot token only in `.env`:

```env
DISCORD_TOKEN=your-token
DISCORD_CHANNEL_ID=your-agent-test-channel-id
ORG_NAME=AOSSIE
```

`DISCORD_CHANNEL_ID` is recommended for the first test. If it is empty, the bot watches text channels whose names contain `agent`, `support`, `gsoc`, or `skill`.

Start it:

```bash
python bot.py
```

## Discord test

Post a normal message in the configured channel:

```text
How do I get started with SkillBot?
```

The expected result is a new thread with a source-backed response. Try an ambiguous question next:

```text
How do I get started?
```

The bot should ask which AOSSIE project you mean. Questions it cannot support are appended to `data/gap_log.json`; all handled events are appended to `data/audit.jsonl`.

## MVP safety boundaries

The bot ignores its own messages, only watches configured channels, does not change roles, does not create GitHub issues, does not use Administrator permission, and does not send writes to GitHub. Repository docs are fetched from public GitHub raw URLs and cached under `data/repos`.

For a production deployment, add a durable database, a scheduled doc sync, a local Ollama service or approved hosted model, retry/backoff, a maintainer approval queue, and the dashboard API adapter.
