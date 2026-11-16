import { randomUUID } from "node:crypto";
import { and, desc, eq } from "drizzle-orm";
import type { Database } from "../client.js";
import {
  conversations,
  type Conversation,
  type ConversationKind,
  type Platform,
} from "../schema.js";

export interface ConversationScope {
  tenantId: string;
  botId: string;
}

export interface EnsureConversationInput extends ConversationScope {
  connectionId: string;
  platform: Platform;
  externalThreadId: string;
  externalChannelId: string;
  kind: ConversationKind;
  title?: string | null;
  participantExternalId?: string | null;
  participantName?: string | null;
  metadata?: Record<string, unknown>;
}

function isUniqueViolation(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const code = (error as { code?: unknown }).code;
  return code === "23505" || code === "unique_violation";
}

export async function ensureConversation(
  db: Database,
  input: EnsureConversationInput,
): Promise<Conversation> {
  const existing = await findConversationByThread(db, {
    tenantId: input.tenantId,
    botId: input.botId,
    connectionId: input.connectionId,
    externalThreadId: input.externalThreadId,
  });

  if (existing) {
    const updates: Partial<typeof conversations.$inferInsert> = {
      externalChannelId: input.externalChannelId,
      kind: input.kind,
      status: "active",
      updatedAt: new Date(),
    };
    if (input.title !== undefined) updates.title = input.title;
    if (input.participantExternalId !== undefined) {
      updates.participantExternalId = input.participantExternalId;
    }
    if (input.participantName !== undefined) {
      updates.participantName = input.participantName;
    }
    if (input.metadata !== undefined) updates.metadata = input.metadata;

    const updated = await db
      .update(conversations)
      .set(updates)
      .where(eq(conversations.id, existing.id))
      .returning();
    return updated[0] ?? existing;
  }

  try {
    const inserted = await db
      .insert(conversations)
      .values({
        id: randomUUID(),
        tenantId: input.tenantId,
        botId: input.botId,
        connectionId: input.connectionId,
        platform: input.platform,
        externalThreadId: input.externalThreadId,
        externalChannelId: input.externalChannelId,
        kind: input.kind,
        title: input.title ?? null,
        participantExternalId: input.participantExternalId ?? null,
        participantName: input.participantName ?? null,
        metadata: input.metadata ?? {},
      })
      .returning();
    return inserted[0]!;
  } catch (error) {
    if (!isUniqueViolation(error)) throw error;
    const raced = await findConversationByThread(db, {
      tenantId: input.tenantId,
      botId: input.botId,
      connectionId: input.connectionId,
      externalThreadId: input.externalThreadId,
    });
    if (!raced) throw error;
    return raced;
  }
}

export async function findConversationByThread(
  db: Database,
  input: ConversationScope & {
    connectionId: string;
    externalThreadId: string;
  },
): Promise<Conversation | null> {
  const rows = await db
    .select()
    .from(conversations)
    .where(
      and(
        eq(conversations.tenantId, input.tenantId),
        eq(conversations.botId, input.botId),
        eq(conversations.connectionId, input.connectionId),
        eq(conversations.externalThreadId, input.externalThreadId),
      ),
    )
    .limit(1);
  return rows[0] ?? null;
}

export async function findConversationById(
  db: Database,
  scope: ConversationScope,
  conversationId: string,
): Promise<Conversation | null> {
  const rows = await db
    .select()
    .from(conversations)
    .where(
      and(
        eq(conversations.tenantId, scope.tenantId),
        eq(conversations.botId, scope.botId),
        eq(conversations.id, conversationId),
      ),
    )
    .limit(1);
  return rows[0] ?? null;
}

export async function listParticipantConversations(
  db: Database,
  scope: ConversationScope & {
    connectionId: string;
    participantExternalId: string;
    limit?: number;
  },
): Promise<Conversation[]> {
  return db
    .select()
    .from(conversations)
    .where(
      and(
        eq(conversations.tenantId, scope.tenantId),
        eq(conversations.botId, scope.botId),
        eq(conversations.connectionId, scope.connectionId),
        eq(conversations.participantExternalId, scope.participantExternalId),
      ),
    )
    .orderBy(desc(conversations.updatedAt))
    .limit(scope.limit ?? 20);
}

export async function touchConversation(
  db: Database,
  scope: ConversationScope,
  conversationId: string,
): Promise<void> {
  await db
    .update(conversations)
    .set({ updatedAt: new Date() })
    .where(
      and(
        eq(conversations.tenantId, scope.tenantId),
        eq(conversations.botId, scope.botId),
        eq(conversations.id, conversationId),
      ),
    );
}
