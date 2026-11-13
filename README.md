# AOSSIE + Stability Nexus AI Front Desk

A Discord front desk for **AOSSIE-Org** and **StabilityNexus**. It answers member and contributor questions from maintainer-approved text and public project docs, creates pending questions for maintainers, and coordinates meetings.

For the AOSSIE rebuild, maintainers and authorized staff are the provider side, while contributors are customers/participants. Provider-wide maintainer knowledge is kept separate from contributor-specific context. The Agent's scheduling, reminders, pending interactions, spam controls, and codebase-understanding quiz are the Discord surface of the same AOSSIE AI Front Desk represented by the companion operator dashboard.

## Run it

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# put the bot token in .env
python bot.py
```

The bot auto-detects which organization a server belongs to from its name and provisions that server. For explicit control, an administrator can run:

```text
/frontdesk setup org:aossie support_channel:#ask-a-question staff_channel:#maintainers staff_role:@Maintainer timezone:Australia/Melbourne
/frontdesk setup org:stability support_channel:#support staff_channel:#staff staff_role:@Maintainer timezone:UTC
/frontdesk status
```

## Discord setup

Enable **Message Content Intent** in the Discord Developer Portal. Invite the bot with `bot` and `applications.commands` scopes. It needs Send Messages, Create Public Threads, Read Message History, and Embed Links. It does not need Administrator.

## What members can do

- `/ask` or mention the bot in a support channel. It creates a thread and keeps context there.
- `/help` lists capabilities.
- `/human` escalates with priority and a conversation summary.
- `/meet availability`, `/meet book`, `/meet list`, `/meet reschedule`, `/meet cancel`.
- DMs work after the member has contacted the bot in an organization server.

## What maintainers can do

- `/knowledge add|list|show|cancel` — plain-text organization-wide or customer-specific knowledge.
- `/pending list|show|answer|dismiss` — answer escalations. Replying to the bot's escalation message in the staff channel also answers it.
- `/staff availability-add|availability-list|availability-remove` — publish weekly slots.
- `/staff schedule` — upcoming bookings.
- `/staff spam-add|spam-remove|spam-list` — block or unblock contacts.
- `/frontdesk setup|status|autosetup`.

## How answers work

1. Provider-entered knowledge is searched first, scoped to the server and member.
2. Public `README.md` / `CONTRIBUTING.md` files from the configured organization catalog are used as supporting context.
3. If confidence is low, the bot records a pending question, tells the member, notifies the staff channel, and keeps the conversation open.
4. A maintainer answer is stored with the chosen scope and sent back to the original conversation. Organization-wide answers also resolve other open questions they genuinely match.

`REPO_DOCS_ENABLED=false` disables public-doc lookup and uses maintainer-entered text only.

## Storage and safety

- SQLite at `data/frontdesk.db`; audit events also append to `data/audit.jsonl`.
- One Discord server is one data boundary. Customer-specific notes are only used for that member.
- Bookings use atomic conflict checks; an existing booking is never moved or cancelled by an availability change.
- Reminders and availability notices are stored in a durable notification queue and retried after failures.
- `DEMO_MODE=true` restricts the instance to `DEMO_ALLOWED_USER_IDS` (maintainers are still allowed).

## Refresh the organization catalog

```powershell
python scripts/build_org_catalog.py
```

This rebuilds `config/orgs.json` from the public GitHub repositories of both organizations.

## Render Web Service deployment

If the Render account does not show Background Worker, deploy this repository as a **Web Service**. The bot starts a small HTTP health server on Render's `PORT` while keeping the Discord Gateway connection alive.

- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`
- Health check path: `/health`
- Required environment variable: `DISCORD_TOKEN`
- Optional variables: `DEFAULT_ORG`, `USE_OLLAMA`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `REPO_DOCS_ENABLED`

Static Site and Workflow are not suitable for this continuously connected bot. A free Web Service may sleep depending on the hosting plan; use an always-on service or VPS for uninterrupted production availability. Render's default filesystem is ephemeral, so attach a persistent disk and point `DATABASE_PATH`, `DOCS_DIR`, and `AUDIT_LOG` at it if you need records to survive restarts.

## Gitcord-style Docker development and always-on deployment

This repository now supports the same operational flow used by Gitcord: develop locally with Docker, persist SQLite in a named volume, and run the same container on an always-on Linux VPS when the computer must be off. The bot only needs outbound HTTPS access to Discord; it does not need an inbound public webhook.

### Local development

```bash
cp .env.example .env
# put DISCORD_TOKEN in .env
docker compose up -d --build
docker compose logs -f agent
```

Stop it with `docker compose down`. Do not run a second copy with the same Discord token while testing, or Discord will disconnect one of the sessions.

### Always-on VPS

```bash
git clone https://github.com/anshulchikhale30-p/aossie-discord-agent.git
cd aossie-discord-agent
cp .env.example .env
# edit .env and add the production DISCORD_TOKEN
docker compose up -d --build
docker compose ps
docker compose logs -f agent
```

The `restart: unless-stopped` policy restarts the Agent after crashes or reboots, and the `agent_data` volume preserves the database, document cache, and audit log. Update it with `git pull && docker compose up -d --build`. Never commit `.env`, and never run the local and VPS copies simultaneously with the same token.

## Codebase-understanding gate for issues and PRs

When a member asks to create an issue, bug report, feature request, contribution, or pull request, the Agent starts a short three-question understanding check before processing the request. The questions cover the repository documentation, what to do when the docs are insufficient, and what a useful issue or PR description must contain.

The member selects answers using Discord buttons. If all answers are correct, the original request continues and the result is stored for that member and organization. If an answer is wrong, the buttons close and the Agent responds:

> That option is not correct. Please re-study the codebase, README, and CONTRIBUTING.md before creating an issue or PR.

The check is stored in SQLite, so a passed member does not have to repeat it for every later issue or PR. This is an onboarding quality gate, not proof that someone understands every line of the repository; maintainers still review issues and pull requests.

## Channel and DM interaction behavior

The Agent no longer creates a thread for every message. In a server, it responds when a member explicitly mentions it in a public or private channel where Discord permissions allow it to read and send messages. Issue, bug-report, feature-request, contribution, and pull-request messages also wake the Agent without a mention so the codebase-understanding quiz can start. Unrelated untagged server messages are ignored to prevent unwanted replies. It replies in the same channel and reuses the same user/channel conversation for follow-ups.

Users can also DM the Agent directly without tagging it. The Agent creates a private default-organization conversation for first-contact DMs and continues there. Server administrators control access using Discord’s normal channel, role, invite, and bot-permission settings; staff-only commands still require staff or administrator roles. Threads remain supported when a user explicitly starts in an existing thread or a maintainer uses a thread.
