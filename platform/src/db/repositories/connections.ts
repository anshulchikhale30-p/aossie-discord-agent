import { and, asc, eq } from "drizzle-orm";
import type { Database } from "../client.js";
import {
  connections,
  type Connection,
  type Platform,
} from "../schema.js";

export interface ConnectionScope {
  tenantId: string;
  botId: string;
}

export async function findConnectionByExternalId(
  db: Database,
  scope: ConnectionScope,
  platform: Platform,
  externalId: string,
): Promise<Connection | null> {
  const rows = await db
    .select()
    .from(connections)
    .where(
      and(
        eq(connections.tenantId, scope.tenantId),
        eq(connections.botId, scope.botId),
        eq(connections.platform, platform),
        eq(connections.externalId, externalId),
      ),
    )
    .limit(1);
  return rows[0] ?? null;
}

export async function findConnectionById(
  db: Database,
  scope: ConnectionScope,
  connectionId: string,
): Promise<Connection | null> {
  const rows = await db
    .select()
    .from(connections)
    .where(
      and(
        eq(connections.tenantId, scope.tenantId),
        eq(connections.botId, scope.botId),
        eq(connections.id, connectionId),
      ),
    )
    .limit(1);
  return rows[0] ?? null;
}

export async function listConnections(
  db: Database,
  scope: ConnectionScope,
): Promise<Connection[]> {
  return db
    .select()
    .from(connections)
    .where(
      and(
        eq(connections.tenantId, scope.tenantId),
        eq(connections.botId, scope.botId),
      ),
    )
    .orderBy(asc(connections.platform), asc(connections.createdAt));
}

/**
 * The provider maintainer channel is a Discord channel. A platform without its
 * own maintainer channel, such as WhatsApp, escalates to the Discord connection
 * so every customer surface reaches the same private queue.
 */
export async function findMaintainerConnection(
  db: Database,
  scope: ConnectionScope,
): Promise<Connection | null> {
  const rows = await listConnections(db, scope);
  return (
    rows.find(
      (row) => row.platform === "discord" && row.maintainerChannelId !== null,
    ) ??
    rows.find((row) => row.maintainerChannelId !== null) ??
    null
  );
}

export async function updateConnectionMaintainerChannel(
  db: Database,
  scope: ConnectionScope,
  connectionId: string,
  maintainerChannelId: string | null,
): Promise<Connection | null> {
  const rows = await db
    .update(connections)
    .set({ maintainerChannelId, updatedAt: new Date() })
    .where(
      and(
        eq(connections.tenantId, scope.tenantId),
        eq(connections.botId, scope.botId),
        eq(connections.id, connectionId),
      ),
    )
    .returning();
  return rows[0] ?? null;
}
