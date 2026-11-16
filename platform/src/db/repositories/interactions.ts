import { randomUUID } from "node:crypto";
import { and, asc, desc, eq, inArray } from "drizzle-orm";
import type { Database } from "../client.js";
import {
  interactions,
  type Interaction,
  type InteractionPriority,
  type InteractionStatus,
} from "../schema.js";

export interface InteractionScope {
  tenantId: string;
  botId: string;
}

export interface CreateInteractionInput extends InteractionScope {
  conversationId: string;
  sourceMessageId?: string | null;
  question: string;
  context?: string | null;
  priority?: InteractionPriority;
  dedupeKey: string;
  maintainerConnectionId?: string | null;
  maintainerChannelId?: string | null;
  maintainerThreadId?: string | null;
  maintainerMessageId?: string | null;
  metadata?: Record<string, unknown>;
}

export interface CreateInteractionResult {
  interaction: Interaction;
  inserted: boolean;
}

export const OPEN_INTERACTION_STATUSES: InteractionStatus[] = [
  "open",
  "waiting_for_maintainer",
  "response_received",
];

function isUniqueViolation(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const code = (error as { code?: unknown }).code;
  return code === "23505" || code === "unique_violation";
}

export async function createInteraction(
  db: Database,
  input: CreateInteractionInput,
): Promise<CreateInteractionResult> {
  const existing = await findInteractionByDedupeKey(db, input);
  if (existing) return { interaction: existing, inserted: false };

  try {
    const inserted = await db
      .insert(interactions)
      .values({
        id: randomUUID(),
        tenantId: input.tenantId,
        botId: input.botId,
        conversationId: input.conversationId,
        sourceMessageId: input.sourceMessageId ?? null,
        question: input.question,
        context: input.context ?? null,
        status: input.maintainerMessageId
          ? "waiting_for_maintainer"
          : "open",
        priority: input.priority ?? "normal",
        dedupeKey: input.dedupeKey,
        maintainerConnectionId: input.maintainerConnectionId ?? null,
        maintainerChannelId: input.maintainerChannelId ?? null,
        maintainerThreadId: input.maintainerThreadId ?? null,
        maintainerMessageId: input.maintainerMessageId ?? null,
        metadata: input.metadata ?? {},
      })
      .returning();
    return { interaction: inserted[0]!, inserted: true };
  } catch (error) {
    if (!isUniqueViolation(error)) throw error;
    const raced = await findInteractionByDedupeKey(db, input);
    if (!raced) throw error;
    return { interaction: raced, inserted: false };
  }
}

export async function findInteractionByDedupeKey(
  db: Database,
  scope: InteractionScope & { dedupeKey: string },
): Promise<Interaction | null> {
  const rows = await db
    .select()
    .from(interactions)
    .where(
      and(
        eq(interactions.tenantId, scope.tenantId),
        eq(interactions.botId, scope.botId),
        eq(interactions.dedupeKey, scope.dedupeKey),
      ),
    )
    .limit(1);
  return rows[0] ?? null;
}

export async function findInteractionById(
  db: Database,
  scope: InteractionScope,
  interactionId: string,
): Promise<Interaction | null> {
  const rows = await db
    .select()
    .from(interactions)
    .where(
      and(
        eq(interactions.tenantId, scope.tenantId),
        eq(interactions.botId, scope.botId),
        eq(interactions.id, interactionId),
      ),
    )
    .limit(1);
  return rows[0] ?? null;
}

export async function findInteractionByMaintainerMessageId(
  db: Database,
  scope: InteractionScope,
  maintainerMessageId: string,
): Promise<Interaction | null> {
  const rows = await db
    .select()
    .from(interactions)
    .where(
      and(
        eq(interactions.tenantId, scope.tenantId),
        eq(interactions.botId, scope.botId),
        eq(interactions.maintainerMessageId, maintainerMessageId),
        inArray(interactions.status, OPEN_INTERACTION_STATUSES),
      ),
    )
    .limit(1);
  return rows[0] ?? null;
}

export async function findInteractionByMaintainerThreadId(
  db: Database,
  scope: InteractionScope,
  maintainerThreadId: string,
): Promise<Interaction | null> {
  const rows = await db
    .select()
    .from(interactions)
    .where(
      and(
        eq(interactions.tenantId, scope.tenantId),
        eq(interactions.botId, scope.botId),
        eq(interactions.maintainerThreadId, maintainerThreadId),
        inArray(interactions.status, OPEN_INTERACTION_STATUSES),
      ),
    )
    .orderBy(desc(interactions.createdAt))
    .limit(1);
  return rows[0] ?? null;
}

export async function findLatestOpenInteractionForChannel(
  db: Database,
  scope: InteractionScope & { maintainerChannelId: string },
): Promise<Interaction | null> {
  const rows = await db
    .select()
    .from(interactions)
    .where(
      and(
        eq(interactions.tenantId, scope.tenantId),
        eq(interactions.botId, scope.botId),
        eq(interactions.maintainerChannelId, scope.maintainerChannelId),
        inArray(interactions.status, OPEN_INTERACTION_STATUSES),
      ),
    )
    .orderBy(desc(interactions.createdAt))
    .limit(1);
  return rows[0] ?? null;
}

export async function listOpenInteractions(
  db: Database,
  scope: InteractionScope & {
    maintainerChannelId?: string;
    limit?: number;
  },
): Promise<Interaction[]> {
  const conditions = [
    eq(interactions.tenantId, scope.tenantId),
    eq(interactions.botId, scope.botId),
    inArray(interactions.status, OPEN_INTERACTION_STATUSES),
  ];
  if (scope.maintainerChannelId) {
    conditions.push(
      eq(interactions.maintainerChannelId, scope.maintainerChannelId),
    );
  }

  return db
    .select()
    .from(interactions)
    .where(and(...conditions))
    .orderBy(asc(interactions.createdAt))
    .limit(scope.limit ?? 25);
}

export async function setInteractionNotification(
  db: Database,
  scope: InteractionScope,
  interactionId: string,
  notification: {
    maintainerConnectionId?: string | null;
    maintainerChannelId?: string | null;
    maintainerThreadId?: string | null;
    maintainerMessageId?: string | null;
    status?: InteractionStatus;
  },
): Promise<Interaction | null> {
  const rows = await db
    .update(interactions)
    .set({
      ...notification,
      status: notification.status ?? "waiting_for_maintainer",
      updatedAt: new Date(),
    })
    .where(
      and(
        eq(interactions.tenantId, scope.tenantId),
        eq(interactions.botId, scope.botId),
        eq(interactions.id, interactionId),
      ),
    )
    .returning();
  return rows[0] ?? null;
}

export async function recordInteractionAnswer(
  db: Database,
  scope: InteractionScope,
  interactionId: string,
  answer: {
    responseText: string;
    respondedByExternalId?: string | null;
    status?: InteractionStatus;
  },
): Promise<Interaction | null> {
  const rows = await db
    .update(interactions)
    .set({
      responseText: answer.responseText,
      respondedByExternalId: answer.respondedByExternalId ?? null,
      respondedAt: new Date(),
      status: answer.status ?? "response_received",
      updatedAt: new Date(),
    })
    .where(
      and(
        eq(interactions.tenantId, scope.tenantId),
        eq(interactions.botId, scope.botId),
        eq(interactions.id, interactionId),
      ),
    )
    .returning();
  return rows[0] ?? null;
}

export async function resolveInteraction(
  db: Database,
  scope: InteractionScope,
  interactionId: string,
): Promise<Interaction | null> {
  const rows = await db
    .update(interactions)
    .set({
      status: "resolved",
      resolvedAt: new Date(),
      updatedAt: new Date(),
    })
    .where(
      and(
        eq(interactions.tenantId, scope.tenantId),
        eq(interactions.botId, scope.botId),
        eq(interactions.id, interactionId),
      ),
    )
    .returning();
  return rows[0] ?? null;
}

export async function cancelInteraction(
  db: Database,
  scope: InteractionScope,
  interactionId: string,
): Promise<Interaction | null> {
  const rows = await db
    .update(interactions)
    .set({
      status: "cancelled",
      resolvedAt: new Date(),
      updatedAt: new Date(),
    })
    .where(
      and(
        eq(interactions.tenantId, scope.tenantId),
        eq(interactions.botId, scope.botId),
        eq(interactions.id, interactionId),
      ),
    )
    .returning();
  return rows[0] ?? null;
}
