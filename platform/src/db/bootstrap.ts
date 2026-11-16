import { randomUUID } from "node:crypto";
import { and, eq } from "drizzle-orm";
import type { AppConfig } from "../config.js";
import type { Database } from "./client.js";
import {
  bots,
  connections,
  tenants,
  type Bot,
  type Connection,
  type Platform,
  type Tenant,
} from "./schema.js";

export interface BootstrapResult {
  tenant: Tenant;
  bot: Bot;
  connections: Connection[];
}

export interface ConnectionSeed {
  platform: Platform;
  externalId: string;
  displayName: string;
  maintainerChannelId?: string | null;
  capabilities?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

function isUniqueViolation(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const code = (error as { code?: unknown }).code;
  return code === "23505" || code === "unique_violation";
}

async function ensureTenant(
  db: Database,
  slug: string,
  name: string,
): Promise<Tenant> {
  const existing = await db
    .select()
    .from(tenants)
    .where(eq(tenants.slug, slug))
    .limit(1);
  if (existing[0]) {
    if (existing[0].name === name) return existing[0];
    const updated = await db
      .update(tenants)
      .set({ name, updatedAt: new Date() })
      .where(eq(tenants.id, existing[0].id))
      .returning();
    return updated[0] ?? existing[0];
  }

  try {
    const inserted = await db
      .insert(tenants)
      .values({ id: randomUUID(), slug, name })
      .returning();
    return inserted[0]!;
  } catch (error) {
    if (!isUniqueViolation(error)) throw error;
    const raced = await db
      .select()
      .from(tenants)
      .where(eq(tenants.slug, slug))
      .limit(1);
    if (!raced[0]) throw error;
    return raced[0];
  }
}

async function ensureBot(
  db: Database,
  tenantId: string,
  slug: string,
  name: string,
  systemPrompt: string | null,
): Promise<Bot> {
  const existing = await db
    .select()
    .from(bots)
    .where(and(eq(bots.tenantId, tenantId), eq(bots.slug, slug)))
    .limit(1);

  if (existing[0]) {
    if (
      existing[0].name !== name ||
      existing[0].systemPrompt !== systemPrompt
    ) {
      const updated = await db
        .update(bots)
        .set({ name, systemPrompt, updatedAt: new Date() })
        .where(eq(bots.id, existing[0].id))
        .returning();
      return updated[0] ?? existing[0];
    }
    return existing[0];
  }

  try {
    const inserted = await db
      .insert(bots)
      .values({
        id: randomUUID(),
        tenantId,
        slug,
        name,
        systemPrompt,
      })
      .returning();
    return inserted[0]!;
  } catch (error) {
    if (!isUniqueViolation(error)) throw error;
    const raced = await db
      .select()
      .from(bots)
      .where(and(eq(bots.tenantId, tenantId), eq(bots.slug, slug)))
      .limit(1);
    if (!raced[0]) throw error;
    return raced[0];
  }
}

async function ensureConnection(
  db: Database,
  tenantId: string,
  botId: string,
  seed: ConnectionSeed,
): Promise<Connection> {
  const existing = await db
    .select()
    .from(connections)
    .where(
      and(
        eq(connections.tenantId, tenantId),
        eq(connections.botId, botId),
        eq(connections.platform, seed.platform),
        eq(connections.externalId, seed.externalId),
      ),
    )
    .limit(1);

  if (existing[0]) {
    const current = existing[0];
    const changed =
      current.displayName !== seed.displayName ||
      (current.maintainerChannelId ?? null) !==
        (seed.maintainerChannelId ?? null) ||
      current.status !== "active";
    if (!changed) return current;

    const updated = await db
      .update(connections)
      .set({
        displayName: seed.displayName,
        maintainerChannelId: seed.maintainerChannelId ?? null,
        status: "active",
        capabilities: seed.capabilities ?? current.capabilities,
        metadata: seed.metadata ?? current.metadata,
        updatedAt: new Date(),
      })
      .where(eq(connections.id, current.id))
      .returning();
    return updated[0] ?? current;
  }

  try {
    const inserted = await db
      .insert(connections)
      .values({
        id: randomUUID(),
        tenantId,
        botId,
        platform: seed.platform,
        externalId: seed.externalId,
        displayName: seed.displayName,
        maintainerChannelId: seed.maintainerChannelId ?? null,
        capabilities: seed.capabilities ?? {},
        metadata: seed.metadata ?? {},
      })
      .returning();
    return inserted[0]!;
  } catch (error) {
    if (!isUniqueViolation(error)) throw error;
    const raced = await db
      .select()
      .from(connections)
      .where(
        and(
          eq(connections.tenantId, tenantId),
          eq(connections.botId, botId),
          eq(connections.platform, seed.platform),
          eq(connections.externalId, seed.externalId),
        ),
      )
      .limit(1);
    if (!raced[0]) throw error;
    return raced[0];
  }
}

export function connectionSeedsFromConfig(config: AppConfig): ConnectionSeed[] {
  const seeds: ConnectionSeed[] = [];

  if (config.discord) {
    seeds.push({
      platform: "discord",
      externalId: config.discord.applicationId,
      displayName: `${config.botName} (Discord)`,
      maintainerChannelId: config.discord.maintainerChannelId,
      capabilities: {
        directMessages: true,
        guildChannels: true,
        maintainerChannel: config.discord.maintainerChannelId !== null,
      },
      metadata: {
        applicationId: config.discord.applicationId,
        respondToChannelIds: config.discord.respondToChannelIds,
      },
    });
  }

  if (config.whatsapp) {
    seeds.push({
      platform: "whatsapp",
      externalId: config.whatsapp.phoneNumberId,
      displayName: `${config.botName} (WhatsApp)`,
      maintainerChannelId: null,
      capabilities: {
        directMessages: true,
        maintainerChannel: false,
      },
      metadata: {
        phoneNumberId: config.whatsapp.phoneNumberId,
      },
    });
  }

  return seeds;
}

/**
 * Idempotently creates the single tenant, bot, and platform connections that
 * this deployment serves. The dashboard will replace this with explicit
 * tenant/bot management; the schema already carries the scope columns.
 */
export async function ensureBootstrap(
  db: Database,
  config: AppConfig,
): Promise<BootstrapResult> {
  const tenant = await ensureTenant(db, config.tenantSlug, config.tenantName);
  const bot = await ensureBot(
    db,
    tenant.id,
    config.botSlug,
    config.botName,
    config.botSystemPrompt,
  );

  const seeded: Connection[] = [];
  for (const seed of connectionSeedsFromConfig(config)) {
    seeded.push(await ensureConnection(db, tenant.id, bot.id, seed));
  }

  return { tenant, bot, connections: seeded };
}
