import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";
import { drizzle } from "drizzle-orm/pglite";
import { migrate } from "drizzle-orm/pglite/migrator";
import type { AppConfig } from "../src/config.js";
import type { RequestScope } from "../src/auth/scope.js";
import type { Database } from "../src/db/client.js";
import {
  bots,
  connections,
  tenants,
  type Conversation,
  type ConversationKind,
  type Platform,
} from "../src/db/schema.js";
import { ensureConversation } from "../src/db/repositories/conversations.js";
import * as schema from "../src/db/schema.js";

const migrationsFolder = fileURLToPath(
  new URL("../drizzle", import.meta.url),
);

export interface TestDatabase {
  db: Database;
  client: PGlite;
  close(): Promise<void>;
}

export async function createTestDatabase(): Promise<TestDatabase> {
  const client = new PGlite();
  const rawDb = drizzle(client, { schema });
  await migrate(rawDb, { migrationsFolder });
  const db = rawDb as unknown as Database;

  return {
    db,
    client,
    async close() {
      await client.close();
    },
  };
}

export interface TenantScope {
  tenantId: string;
  botId: string;
  connectionId: string;
  connectionExternalId: string;
}

export interface CreateTenantScopeOptions {
  platform?: Platform;
  externalId?: string;
  maintainerChannelId?: string | null;
}

export async function createTenantScope(
  db: Database,
  options: CreateTenantScopeOptions = {},
): Promise<TenantScope> {
  const tenantId = randomUUID();
  const botId = randomUUID();
  const connectionId = randomUUID();
  const platform = options.platform ?? "discord";
  const externalId = options.externalId ?? `external-${connectionId}`;

  await db.insert(tenants).values({
    id: tenantId,
    slug: `tenant-${tenantId}`,
    name: "Test Tenant",
  });
  await db.insert(bots).values({
    id: botId,
    tenantId,
    slug: `bot-${botId}`,
    name: "Test Bot",
  });
  await db.insert(connections).values({
    id: connectionId,
    tenantId,
    botId,
    platform,
    externalId,
    displayName: `${platform} test`,
    maintainerChannelId: options.maintainerChannelId ?? null,
  });

  return {
    tenantId,
    botId,
    connectionId,
    connectionExternalId: externalId,
  };
}

export interface CreateConversationOptions {
  externalThreadId?: string;
  externalChannelId?: string;
  kind?: ConversationKind;
  participantExternalId?: string | null;
  participantName?: string | null;
  platform?: Platform;
}

export async function createConversation(
  db: Database,
  scope: TenantScope,
  options: CreateConversationOptions = {},
): Promise<Conversation> {
  const platform = options.platform ?? "discord";
  const externalThreadId =
    options.externalThreadId ?? `discord:guild-1:channel-${randomUUID()}`;
  return ensureConversation(db, {
    tenantId: scope.tenantId,
    botId: scope.botId,
    connectionId: scope.connectionId,
    platform,
    externalThreadId,
    externalChannelId:
      options.externalChannelId ?? externalThreadId.split(":").slice(0, 3).join(":"),
    kind: options.kind ?? "dm",
    participantExternalId:
      options.participantExternalId ?? `customer-${randomUUID()}`,
    participantName: options.participantName ?? "Test Customer",
  });
}

export function scopeFor(
  scope: TenantScope,
  conversation: Conversation,
  role: RequestScope["role"] = "customer",
  overrides: Partial<RequestScope> = {},
): RequestScope {
  return {
    tenantId: scope.tenantId,
    botId: scope.botId,
    connectionId: scope.connectionId,
    conversationId: conversation.id,
    platform: conversation.platform,
    externalUserId: conversation.participantExternalId ?? "customer-unknown",
    externalThreadId: conversation.externalThreadId,
    role,
    displayName: conversation.participantName,
    ...overrides,
  };
}

export function testConfig(overrides: Partial<AppConfig> = {}): AppConfig {
  return {
    nodeEnv: "test",
    databaseUrl: "postgres://unused",
    tenantSlug: "test-tenant",
    tenantName: "Test Tenant",
    botSlug: "test-bot",
    botName: "Test Bot",
    botSystemPrompt: null,
    discord: {
      botToken: "token",
      publicKey: "public-key",
      applicationId: "discord-app",
      maintainerChannelId: "discord:unknown:maintainer-channel",
      maintainerChannelKey: "maintainer-channel",
      respondToChannelIds: ["maintainer-channel"],
      gatewayWebhookUrl: "http://127.0.0.1:3000/eve/v1/discord",
      gatewayDurationMs: 60_000,
    },
    whatsapp: null,
    publicBaseUrl: null,
    ...overrides,
  };
}
