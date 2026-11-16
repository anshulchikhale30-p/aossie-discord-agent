# AOSSIE Front Desk (`platform/`)

An AI front desk for **Discord** and **WhatsApp**, built on [EVE](https://eve.dev), the
[Vercel Chat SDK](https://chat-sdk.dev), PostgreSQL/Drizzle, and a
K3s/CloudNativePG/Flux deployment baseline.

The package has two jobs:

- a **reusable front-desk library** (`src/`) for tenant/bot-scoped conversations,
  messages, knowledge, escalations, and Chat SDK delivery;
- a **reference agent** (`agent/`) that answers customers only from provider-supplied
  context, escalates unanswered questions to a private maintainer channel, and relays
  maintainer answers back to the customer.

This is an MVP. It deliberately covers Discord + WhatsApp only; the dashboard, web
client, and multi-tenant management UI are follow-up work. The database schema is
already tenant/bot scoped so those can be added without a rewrite.

---

## Architecture

```text
Discord / WhatsApp
        │
        │  webhook (verified by the Chat SDK adapter)
        │  Discord regular messages also arrive through the Gateway listener
        ▼
agent/channels/chat.ts
  ├─ resolve the tenant, bot, and platform connection from the verified event
  ├─ upsert the canonical conversation
  ├─ persist the inbound message with a dedupe key
  ├─ build trusted session auth (tenant, bot, connection, conversation, role)
  └─ send the message to EVE
        │
        ▼
EVE agent (agent/agent.ts)
  ├─ instructions: answer only from provider context, reuse prior answers,
  │  classify knowledge, escalate when needed
  ├─ tools: search_knowledge, search_conversation_history, save_knowledge,
  │  escalate_to_maintainers, list_open_interactions, answer_interaction
  └─ Postgres workflow world for durable multi-turn sessions
        │
        ▼
content.completed
  ├─ persist the outbound message
  └─ post the final reply through Chat SDK (streaming is disabled)
```

Escalation path:

```text
Customer question
  → no answer in knowledge / history, or needs an account action
  → escalate_to_maintainers
      → interactions row (open)
      → post to the private Discord maintainer channel
  → maintainer replies in that channel
      → answer_interaction
          → optionally save general or user-specific knowledge
          → relay the answer to the customer's original thread
          → close the interaction
```

The trusted scope (tenant, bot, connection, conversation, role, external user) is
derived from the verified adapter event and stored in the EVE session auth. The model
never chooses those values.

---

## Repository layout

| Path | Purpose |
| --- | --- |
| `agent/agent.ts` | Model selection and the Postgres workflow world. |
| `agent/instructions.md` | Customer, escalation, maintainer, and knowledge rules. |
| `agent/channels/chat.ts` | Chat SDK adapters, inbound persistence, maintainer routing, outbound replies. |
| `agent/tools/` | The six EVE tools used by the agent. |
| `src/config.ts` | Environment parsing and platform enablement rules. |
| `src/auth/scope.ts` | Trusted session auth shape and role assertions. |
| `src/db/schema.ts` | Drizzle schema for every tenant/bot-scoped table. |
| `src/db/repositories/` | Portable PostgreSQL repositories (also used by tests through PGlite). |
| `src/db/bootstrap.ts` | Idempotent single-tenant/bot/connection seeding. |
| `src/chat/` | Chat SDK registry and delivery helpers (`postToChannel`, `postToThread`, `relayToCustomer`). |
| `src/runtime.ts` | Process-wide database handle and lazy bootstrap. |
| `src/index.ts` | Library exports. |
| `drizzle/` | Generated SQL migrations. |
| `scripts/discord-gateway.ts` | Long-running Discord Gateway listener that forwards regular messages to EVE. |
| `deploy/k8s/` | Kustomize baseline: app, gateway, CloudNativePG cluster, service, ingress, secrets example. |
| `deploy/flux/` | Flux Kustomizations for the CloudNativePG operator and the app. |
| `deploy/k3d/` | Local k3d cluster config and overlay. See [deploy/k3d/README.md](deploy/k3d/README.md). |
| `tests/` | Vitest suites using PGlite and the real migration. |

---

## Quick start with Docker Compose

Prerequisites: Docker, a model API key, and Discord and/or WhatsApp credentials.

```bash
cd platform
cp .env.example .env
# Edit .env: set AI_GATEWAY_API_KEY (or LLM_*), and the platform credentials.
docker compose up --build
```

The Compose stack starts:

| Service | Role |
| --- | --- |
| `postgres` | PostgreSQL 17 with a persistent volume. |
| `frontdesk` | Migrations, seed, workflow bootstrap, then the EVE server on port 3000. |
| `gateway` | Discord Gateway listener forwarding regular messages to `frontdesk`. |

Check health:

```bash
curl http://localhost:3000/eve/v1/health
# {"ok":true,"status":"ready","workflowId":"workflow//eve//workflowEntry"}
```

Set the public webhook URLs in Discord and Meta:

- Discord Interactions Endpoint URL: `https://<public-host>/eve/v1/discord`
- WhatsApp callback URL: `https://<public-host>/eve/v1/whatsapp`

For local testing, expose port 3000 with a tunnel (Cloudflare Tunnel, ngrok, or
similar) and use the tunnel URL in both consoles. The Discord Gateway listener talks
to the app internally, so it does not need the tunnel.

Stop the stack with `docker compose down` (add `-v` to delete the database volume).

---

## Local development without Docker

Prerequisites: Node.js 24+, pnpm 12+, and PostgreSQL 17.

```bash
cd platform
pnpm install

# Start PostgreSQL however you prefer, for example:
docker run --name frontdesk-postgres \
  -e POSTGRES_USER=frontdesk \
  -e POSTGRES_PASSWORD=frontdesk \
  -e POSTGRES_DB=frontdesk \
  -p 5432:5432 -d postgres:17-alpine

cp .env.example .env
# Edit .env. The defaults point at localhost:5432.

pnpm db:migrate
pnpm db:seed
pnpm workflow:bootstrap

pnpm dev
```

In a second terminal, start the Discord Gateway listener:

```bash
pnpm gateway
```

`pnpm dev` runs `eve dev`. For a production-like local run:

```bash
pnpm build
pnpm start
```

`pnpm build` uses `eve build --skip-sandbox-prewarm` so it does not need a Docker
socket. Use `pnpm build:full` if you add agent features that need a prewarmed sandbox.

### Database and workflow bootstrap

The EVE server needs the workflow world schema before it can start. Run these once per
database (they are idempotent):

```bash
pnpm db:migrate          # this package's tables
pnpm db:seed             # one tenant, one bot, one connection per configured platform
pnpm workflow:bootstrap  # @workflow/world-postgres schema and graphile-worker schema
```

The container entrypoint runs the same steps when `RUN_MIGRATIONS`, `RUN_SEED`, and
`RUN_WORKFLOW_BOOTSTRAP` are `true`.

---

## Configuration

Copy `.env.example` to `.env`. All values are validated by Zod at startup.

### Core

| Variable | Default | Notes |
| --- | --- | --- |
| `NODE_ENV` | `development` | Standard Node environment. |
| `DATABASE_URL` | `postgres://frontdesk:frontdesk@localhost:5432/frontdesk` | Application database. |
| `PUBLIC_BASE_URL` | unset | Public origin, used for documentation/links. |
| `TENANT_SLUG` | `aossie` | Seed tenant slug. |
| `TENANT_NAME` | `AOSSIE` | Seed tenant display name. |
| `BOT_SLUG` | `frontdesk` | Seed bot slug. |
| `BOT_NAME` | `AOSSIE Front Desk` | Seed bot name and Chat SDK username. |
| `BOT_SYSTEM_PROMPT` | unset | Provider-managed prompt appended to `agent/instructions.md`. |

### Model

| Variable | Notes |
| --- | --- |
| `LLM_BASE_URL` | Set to use an OpenAI-compatible endpoint (vLLM, Ollama, OpenRouter, etc.). |
| `LLM_API_KEY` | Optional key for the compatible endpoint. |
| `LLM_MODEL` | Model id. Defaults to `openai/gpt-5.4-mini`. |
| `LLM_CONTEXT_WINDOW` | Model context window in tokens. Defaults to `128000`. |
| `AI_GATEWAY_API_KEY` | Used when `LLM_BASE_URL` is not set; routes `LLM_MODEL` through the Vercel AI Gateway. |

Examples:

```bash
# Vercel AI Gateway
AI_GATEWAY_API_KEY=...
LLM_MODEL=openai/gpt-5.4-mini

# OpenRouter
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=...
LLM_MODEL=openai/gpt-5.4-mini

# Local Ollama
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=llama3.1
LLM_CONTEXT_WINDOW=32768
```

### Discord

| Variable | Notes |
| --- | --- |
| `DISCORD_BOT_TOKEN` | Bot token from the Discord Developer Portal. |
| `DISCORD_PUBLIC_KEY` | Application public key, used to verify interaction webhooks. |
| `DISCORD_APPLICATION_ID` | Application id; also the connection's external id. |
| `DISCORD_MAINTAINER_CHANNEL_ID` | Private maintainer channel. A raw channel id or a full `discord:<guild>:<channel>` id both work. |
| `DISCORD_RESPOND_TO_CHANNEL_IDS` | Comma-separated parent channel ids where the bot answers without a mention, including child threads. DMs and mentions are always answered. The maintainer channel is added automatically. |
| `DISCORD_GATEWAY_WEBHOOK_URL` | Where the Gateway listener forwards regular messages. Defaults to `http://127.0.0.1:3000/eve/v1/discord`. |
| `DISCORD_GATEWAY_DURATION_MS` | How long one Gateway listener session runs before reconnecting. Defaults to 6 hours. |

Discord is enabled only when all three of `DISCORD_BOT_TOKEN`, `DISCORD_PUBLIC_KEY`,
and `DISCORD_APPLICATION_ID` are present.

### WhatsApp

| Variable | Notes |
| --- | --- |
| `WHATSAPP_ACCESS_TOKEN` | Meta Cloud API access token. Prefer a permanent system-user token in production. |
| `WHATSAPP_APP_SECRET` | Meta app secret, used to verify webhook signatures. |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp phone number id; also the connection's external id. |
| `WHATSAPP_VERIFY_TOKEN` | Random string shared with the Meta webhook configuration. |

WhatsApp is enabled only when all four values are present.

### Workflow world

| Variable | Notes |
| --- | --- |
| `WORKFLOW_POSTGRES_URL` | Workflow database. Falls back to `DATABASE_URL`. |
| `WORKFLOW_POSTGRES_MAX_POOL_SIZE` | Workflow connection pool size. |
| `WORKFLOW_POSTGRES_WORKER_CONCURRENCY` | Workflow worker concurrency. |

### Container bootstrap

| Variable | Notes |
| --- | --- |
| `RUN_MIGRATIONS` | Run the Drizzle migration before starting the server. |
| `RUN_SEED` | Run the idempotent tenant/bot/connection seed. |
| `RUN_WORKFLOW_BOOTSTRAP` | Create the workflow schema before starting the server. |

---

## Discord setup

1. Create an application at the [Discord Developer Portal](https://discord.com/developers/applications).
2. Copy **Application ID** and **Public Key** from *General Information*.
3. Create a bot and copy its token from *Bot*. Set `DISCORD_BOT_TOKEN`.
4. Enable the **Message Content** privileged intent under *Bot → Privileged Gateway
   Intents*. The Gateway listener uses Guilds, Guild Messages, Direct Messages,
   Message Content, and reaction intents with `Partials.Channel`.
5. Invite the bot to the server with at least: View Channels, Send Messages, Read
   Message History, Add Reactions, Embed Links, and Attach Files. Add thread
   permissions if you use Discord threads for maintainer conversations.
6. Set **Interactions Endpoint URL** to `https://<public-host>/eve/v1/discord`.
7. Run the Gateway listener (`pnpm gateway`, the Compose `gateway` service, or the
   Kubernetes gateway Deployment). Discord sends regular message content over the
   Gateway, not to the webhook; the listener forwards raw events to the EVE webhook.
   Run exactly one listener per bot token.
8. Create a private maintainer channel, invite the bot, and set
   `DISCORD_MAINTAINER_CHANNEL_ID` to its channel id.

The bot answers DMs and @-mentions everywhere. In guild channels listed in
`DISCORD_RESPOND_TO_CHANNEL_IDS`, it also answers messages that do not mention it.
The maintainer channel is always answered and is treated as the maintainer role, not
as a customer conversation.

### Answering an escalation as a maintainer

The bot posts each escalated question to the maintainer channel with an **Escalation
ID**. A maintainer can reply:

- directly to that escalation message,
- in a thread under it, or
- in the channel when exactly one escalation is open.

When several escalations are open, the bot asks which one is meant and can list them
with `list_open_interactions`. The bot relays the answer to the customer's original
Discord or WhatsApp thread, closes the escalation, and can optionally save the answer
as general or user-specific knowledge.

---

## WhatsApp setup

1. Create a Meta app and add the **WhatsApp** product.
2. Copy the **Phone number ID** and an access token from *WhatsApp → API Setup*. Use a
   permanent system-user token for production.
3. Copy the **App Secret** from *App Settings → Basic*.
4. Choose a random `WHATSAPP_VERIFY_TOKEN` and set it in both `.env` and the Meta
   webhook configuration.
5. Set the callback URL to `https://<public-host>/eve/v1/whatsapp`, enter the verify
   token, and subscribe to the `messages` field.
6. Send a test message to the business number.

WhatsApp is DM-only in this MVP. A WhatsApp customer's escalation is routed to the
**Discord maintainer channel** when Discord is configured, so one private queue serves
both platforms. If Discord is not configured, the escalation tool returns
`no_maintainer_channel` and the bot tells the customer a maintainer will follow up
through another support channel.

---

## How the agent behaves

The hard rule is in `agent/instructions.md`: answer only from provider context, meaning

- entries returned by `search_knowledge`;
- earlier messages returned by `search_conversation_history`;
- an answer a maintainer just gave in the maintainer channel.

It must not use GitHub, READMEs, web pages, search engines, or general knowledge as if
they were provider policy.

### Answer reuse

Answer reuse is a prompt-level behavior, not a separate cache:

1. Search the knowledge base first.
2. If the question is customer-specific, search the customer's user-specific knowledge.
3. Before escalating, search the customer's conversation history. If the question was
   already answered, do not forward it again; acknowledge the earlier answer and ask
   whether more help is needed.
4. If the customer remains unsatisfied or asks for a human, escalate and include what
   was already tried.

### Knowledge scopes

| Scope | Meaning | Who can save it |
| --- | --- | --- |
| `general` | True for every customer: policy, process, public price, FAQ. | Maintainers only. |
| `user` | True for one customer: account status, order, exception. | A customer about themselves; a maintainer with the customer's `interactionId`. |
| `none` | A one-off answer, greeting, guess, or secret. | Not saved. |

The rules are enforced in `src/agent/tool-helpers.ts`, not only in the prompt. The
exact same content is deduplicated per tenant, bot, scope, and subject.

### Escalation lifecycle

`interactions.status` moves through:

```text
open → waiting_for_maintainer → response_received → resolved
                                             ↘ cancelled
```

The interaction stores the source conversation, source message, maintainer connection,
maintainer channel/thread/message, question, context, answer, and timestamps. The
customer's answer relay is idempotent through a `relay:interaction:<id>` message
dedupe key, so retrying `answer_interaction` does not send the answer twice.

### Data model

All tables carry `tenant_id` and `bot_id`; every repository query scopes by both.

| Table | Contents |
| --- | --- |
| `tenants` | Tenant slug/name. |
| `bots` | Bot slug/name and optional provider-managed system prompt. |
| `connections` | One row per platform connection; holds the platform external id and maintainer channel. |
| `conversations` | Canonical thread/DM, participant identity, and platform ids. |
| `messages` | Canonical inbound/outbound messages with dedupe keys and delivery status. |
| `knowledge_entries` | General or user-specific knowledge, with subject and effective/expiry timestamps. |
| `interactions` | Escalations and their maintainer notification/answer state. |
| `audit_events` | Append-only audit trail for escalations, answers, and other actions. |

---

## Deployment: K3s + CloudNativePG + Flux

The baseline in `deploy/k8s` runs:

- the EVE app Deployment and Service;
- a separate Discord Gateway Deployment (one replica, because Discord allows one
  Gateway session per shard/token);
- a CloudNativePG `Cluster` named `frontdesk-postgres`;
- a ConfigMap, an Ingress, and a Secret example.

CloudNativePG creates the application secret `frontdesk-postgres-app` with key `uri`.
The app and gateway read `DATABASE_URL` and `WORKFLOW_POSTGRES_URL` from it.

### 1. Build and publish the image

```bash
docker build -t ghcr.io/<owner>/aossie-frontdesk:<tag> platform
docker push ghcr.io/<owner>/aossie-frontdesk:<tag>
```

Update the image in `deploy/k8s/deployment.yaml` and
`deploy/k8s/gateway-deployment.yaml` (or use a Kustomize `images:` override).

### 2. Install the operator and create the secret

With Flux, apply the operator Kustomization first (see below). Without Flux:

```bash
helm repo add cnpg https://cloudnative-pg.github.io/charts
helm repo update
helm upgrade --install cnpg cnpg/cloudnative-pg \
  --namespace cnpg-system --create-namespace \
  --version 0.29.1
kubectl -n cnpg-system rollout status deploy/cnpg-cloudnative-pg
```

Create the platform/model secret from `deploy/k8s/secret.example.yaml`:

```bash
kubectl apply -f deploy/k8s/namespace.yaml
cp deploy/k8s/secret.example.yaml /tmp/frontdesk-secret.yaml
# Edit /tmp/frontdesk-secret.yaml with real values.
kubectl apply -f /tmp/frontdesk-secret.yaml
```

Do not commit the filled-in secret.

### 3. Apply the app

```bash
kubectl apply -k deploy/k8s
kubectl -n frontdesk wait --for=condition=Ready cluster/frontdesk-postgres --timeout=300s
kubectl -n frontdesk rollout status deploy/frontdesk --timeout=300s
kubectl -n frontdesk rollout status deploy/frontdesk-discord-gateway --timeout=300s
```

Change the Ingress host in `deploy/k8s/ingress.yaml` and configure DNS/TLS for your
cluster. The example uses Traefik (k3s default) and cert-manager.

The app Deployment runs migrations, seed, and workflow bootstrap on startup. They are
idempotent. If you scale the app beyond one replica, move those steps to a Kubernetes
Job and set `RUN_MIGRATIONS`, `RUN_SEED`, and `RUN_WORKFLOW_BOOTSTRAP` to `false` on the
Deployments.

### 4. Flux

`deploy/flux` contains two Flux Kustomizations:

- `cloudnative-pg` installs the operator Helm chart `0.29.1` (operator appVersion
  `1.30.1`) from the CloudNativePG Helm repository;
- `frontdesk` applies `./platform/deploy/k8s` after the operator is ready.

Apply the example GitRepository after replacing the URL with your fork, then apply the
Flux Kustomizations:

```bash
kubectl apply -f deploy/flux/gitrepository.example.yaml
kubectl apply -k deploy/flux
```

Alternatively, point `flux bootstrap` at `./platform/deploy/flux`. For a private
repository, create a Git authentication secret and uncomment `secretRef` in the
GitRepository.

The Flux app path uses the published image from `deploy/k8s`. For local development
with a locally built image, use the k3d overlay described in
[deploy/k3d/README.md](deploy/k3d/README.md).

---

## Using this package as a library

`src/index.ts` exports the configuration, auth, database, Chat SDK, and runtime layers.
The package exposes three entry points:

```json
{
  "exports": {
    ".": "./src/index.ts",
    "./db": "./src/db/index.ts",
    "./chat": "./src/chat/index.ts"
  }
}
```

Example:

```ts
import {
  createDatabase,
  ensureBootstrap,
  ensureConversation,
  loadConfig,
  recordMessage,
  searchKnowledge,
  saveKnowledge,
} from "@aossie/frontdesk";

const config = loadConfig();
const { db, close } = createDatabase(config.databaseUrl);
const { tenant, bot, connections } = await ensureBootstrap(db, config);
const connection = connections[0]!;

const conversation = await ensureConversation(db, {
  tenantId: tenant.id,
  botId: bot.id,
  connectionId: connection.id,
  platform: connection.platform,
  externalThreadId: "discord:guild-1:channel-1",
  externalChannelId: "discord:guild-1:channel-1",
  kind: "group",
  participantExternalId: "customer-1",
  participantName: "Ada",
});

await recordMessage(db, {
  tenantId: tenant.id,
  botId: bot.id,
  conversationId: conversation.id,
  direction: "inbound",
  content: "What is the refund window?",
  dedupeKey: "discord-message-1",
});

await saveKnowledge(db, {
  tenantId: tenant.id,
  botId: bot.id,
  scope: "general",
  title: "Refund window",
  content: "Refunds are available within 30 days.",
});

const matches = await searchKnowledge(db, {
  tenantId: tenant.id,
  botId: bot.id,
  connectionId: connection.id,
  externalUserId: "customer-1",
  query: "refund",
});

await close();
```

The exports point at TypeScript source and are intended for a workspace or a bundler.
`pnpm build` builds the reference EVE agent, not a separately published npm package.
Splitting `src/` into its own package is a follow-up step; the code is already kept
free of agent imports so the move is mechanical.

Delivery helpers are available from `@aossie/frontdesk/chat`:

```ts
import { postToChannel, postToThread, relayToCustomer } from "@aossie/frontdesk/chat";

await postToChannel("discord:guild-1:channel-1", "Hello from the front desk");
```

They use the Chat SDK runtime registered by `agent/channels/chat.ts`, so they must run
inside the same process as the channel module.

---

## Tests and checks

```bash
pnpm test        # Vitest + PGlite, real Drizzle migration, no external Postgres
pnpm typecheck   # tsc --noEmit
pnpm build       # eve build --skip-sandbox-prewarm
```

The test suites cover:

- tenant/bot isolation for conversations, messages, knowledge, and interactions;
- knowledge scope rules (general vs user, customer vs maintainer, identity per connection);
- escalation dedupe, notification state, answer relay, and resolution;
- canonical message dedupe, history search, and delivery status;
- idempotent bootstrap and platform connection seeding;
- environment validation and Discord channel-id handling;
- trusted auth scope parsing and role assertions.

The implementation was also validated against a real PostgreSQL instance: migrations,
seed, workflow bootstrap, EVE server startup, and `GET /eve/v1/health` returning
`{"ok":true,"status":"ready"}`.

---

## Spec compliance and deviations

Implemented as specified:

- Discord + WhatsApp only, using EVE, Chat SDK, PostgreSQL/Drizzle, and
  K3s/CloudNativePG/Flux.
- Provider-supplied knowledge only; no GitHub/README/web retrieval.
- General vs user-specific knowledge, with answer reuse governed by the system prompt.
- Private maintainer channel, maintainer replies, and relay to the customer.
- Tenant/bot columns everywhere, seeded as one tenant/bot from environment config.
- Reusable library exports and a deployable reference baseline.

Deliberate MVP deviations and decisions:

1. **Single tenant/bot from environment config.** The schema and repositories are
   multi-tenant, but there is no dashboard or tenant-management API yet.
2. **No web client.** The Discord workflow is the first validated surface, as agreed.
3. **No dashboard.** Knowledge and escalations are managed through the chat tools; SQL
   is available for operators. A dashboard can be added on top of the same schema.
4. **Answer reuse is prompt-level.** There is no separate answer-cache table or feature;
   the prompt plus `search_knowledge` and `search_conversation_history` implement the
   agreed behavior.
5. **The maintainer channel is Discord.** WhatsApp has no private channel primitive in
   this MVP, so WhatsApp escalations route to the same Discord maintainer channel.
6. **Discord regular messages require the Gateway listener.** Discord webhooks deliver
   interactions, but message content is a Gateway event. The listener is a separate
   process/Deployment; run exactly one per bot token.
7. **Streaming is disabled** for both platforms so each turn posts one final message and
   the canonical outbound record stays in lockstep with the visible reply.
8. **`build` skips sandbox prewarm.** This keeps Docker builds socket-free. Use
   `build:full` if future agent features need a prewarmed sandbox.
9. **Platform onboarding specifics are out of scope.** Test accounts, Meta business
   verification, and production app review are operational tasks, not package code.
10. **The default model id is a placeholder.** Set `LLM_MODEL` (and `LLM_BASE_URL` or
    `AI_GATEWAY_API_KEY`) for the provider you actually use.
11. **No Python bot integration.** `platform/` is an independent rewrite; the existing
    `bot.py` is left untouched.
12. **Repository search is lexical, not vector-based.** `search_knowledge` and
    `search_conversation_history` use token scoring. A vector index can replace the
    repository internals without changing the tools or schema.

---

## Troubleshooting

**The server exits with `ECONNREFUSED` on startup.**
PostgreSQL is not reachable, or the workflow schema is missing. Check `DATABASE_URL`,
then run `pnpm db:migrate`, `pnpm db:seed`, and `pnpm workflow:bootstrap`.

**`Invalid compiled eve artifact: compiled binding "channels/chat.ts" is not referenced
by its node manifest`.**
EVE derives webhook routes at build time. Both Discord and WhatsApp adapters must be
registered unconditionally, with placeholder credentials when a platform is
unconfigured. Do not make the adapter map conditional.

**Discord mentions work but regular messages do not.**
The Gateway listener is not running, the Message Content intent is disabled, or the
listener cannot reach `DISCORD_GATEWAY_WEBHOOK_URL`. Check the gateway logs and the
intent settings.

**Maintainer replies are treated as customer messages.**
`DISCORD_MAINTAINER_CHANNEL_ID` does not match the channel's raw id. Both a raw id and
a full `discord:<guild>:<channel>` id are accepted; the raw channel segment is what
inbound events are matched against. The bot must be able to read and post in that
channel.

**WhatsApp verification fails.**
The callback URL must be public HTTPS, the verify token must match exactly, and the
webhook must be subscribed to `messages`.

**`pnpm build:full` fails without Docker.**
It prewarms an EVE sandbox and needs a Docker socket. Use `pnpm build` for normal
builds.

**The Graphile Worker warns about executable detection on Windows.**
This is a harmless Windows-only warning from `graphile-worker`; the workflow still runs.

---

## Security notes

- Never commit `.env` or a filled-in `secret.yaml`. They are ignored by `.gitignore`.
- The maintainer channel is trusted by channel id. Keep it private and restrict who can
  post there.
- Tenant/bot/connection/conversation scope comes from verified adapter events and
  session auth, never from model output.
- Knowledge is provider-supplied. Do not paste secrets, tokens, or another customer's
  data into knowledge entries.
- Rotate Discord/WhatsApp/model credentials if they are exposed.
- The audit table records escalation and answer actions; extend it before adding
  destructive dashboard operations.
