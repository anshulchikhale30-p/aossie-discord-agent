import { randomUUID } from "node:crypto";
import { and, asc, desc, eq, inArray } from "drizzle-orm";
import type { Database } from "../client.js";
import {
  messages,
  type DeliveryStatus,
  type Message,
  type MessageDirection,
} from "../schema.js";

export interface MessageScope {
  tenantId: string;
  botId: string;
}

export interface RecordMessageInput extends MessageScope {
  conversationId: string;
  externalMessageId?: string | null;
  direction: MessageDirection;
  authorExternalId?: string | null;
  authorName?: string | null;
  content: string;
  contentJson?: Record<string, unknown> | null;
  dedupeKey: string;
  deliveryStatus?: DeliveryStatus;
  metadata?: Record<string, unknown>;
}

export interface RecordMessageResult {
  message: Message;
  inserted: boolean;
}

export async function recordMessage(
  db: Database,
  input: RecordMessageInput,
): Promise<RecordMessageResult> {
  const inserted = await db
    .insert(messages)
    .values({
      id: randomUUID(),
      tenantId: input.tenantId,
      botId: input.botId,
      conversationId: input.conversationId,
      externalMessageId: input.externalMessageId ?? null,
      direction: input.direction,
      authorExternalId: input.authorExternalId ?? null,
      authorName: input.authorName ?? null,
      content: input.content,
      contentJson: input.contentJson ?? null,
      dedupeKey: input.dedupeKey,
      deliveryStatus: input.deliveryStatus ?? "sent",
      metadata: input.metadata ?? {},
    })
    .onConflictDoNothing({
      target: [messages.conversationId, messages.dedupeKey],
    })
    .returning();

  if (inserted[0]) {
    return { message: inserted[0], inserted: true };
  }

  const existing = await findMessageByDedupeKey(db, {
    tenantId: input.tenantId,
    botId: input.botId,
    conversationId: input.conversationId,
    dedupeKey: input.dedupeKey,
  });
  if (!existing) {
    throw new Error(
      `Failed to record message and could not find the existing row for ${input.dedupeKey}`,
    );
  }
  return { message: existing, inserted: false };
}

export async function findMessageByDedupeKey(
  db: Database,
  input: MessageScope & { conversationId: string; dedupeKey: string },
): Promise<Message | null> {
  const rows = await db
    .select()
    .from(messages)
    .where(
      and(
        eq(messages.tenantId, input.tenantId),
        eq(messages.botId, input.botId),
        eq(messages.conversationId, input.conversationId),
        eq(messages.dedupeKey, input.dedupeKey),
      ),
    )
    .limit(1);
  return rows[0] ?? null;
}

export async function updateMessageDeliveryStatus(
  db: Database,
  scope: MessageScope,
  messageId: string,
  deliveryStatus: DeliveryStatus,
  externalMessageId?: string | null,
): Promise<void> {
  const updates: Partial<typeof messages.$inferInsert> = {
    deliveryStatus,
    updatedAt: new Date(),
  };
  if (externalMessageId !== undefined) {
    updates.externalMessageId = externalMessageId;
  }
  await db
    .update(messages)
    .set(updates)
    .where(
      and(
        eq(messages.tenantId, scope.tenantId),
        eq(messages.botId, scope.botId),
        eq(messages.id, messageId),
      ),
    );
}

export async function findMessageById(
  db: Database,
  scope: MessageScope,
  messageId: string,
): Promise<Message | null> {
  const rows = await db
    .select()
    .from(messages)
    .where(
      and(
        eq(messages.tenantId, scope.tenantId),
        eq(messages.botId, scope.botId),
        eq(messages.id, messageId),
      ),
    )
    .limit(1);
  return rows[0] ?? null;
}

export async function findLatestInboundMessage(
  db: Database,
  scope: MessageScope & { conversationId: string },
): Promise<Message | null> {
  const rows = await db
    .select()
    .from(messages)
    .where(
      and(
        eq(messages.tenantId, scope.tenantId),
        eq(messages.botId, scope.botId),
        eq(messages.conversationId, scope.conversationId),
        eq(messages.direction, "inbound"),
      ),
    )
    .orderBy(desc(messages.createdAt))
    .limit(1);
  return rows[0] ?? null;
}

export async function listConversationMessages(
  db: Database,
  scope: MessageScope & {
    conversationId: string;
    limit?: number;
    before?: Date;
  },
): Promise<Message[]> {
  const rows = await db
    .select()
    .from(messages)
    .where(
      and(
        eq(messages.tenantId, scope.tenantId),
        eq(messages.botId, scope.botId),
        eq(messages.conversationId, scope.conversationId),
      ),
    )
    .orderBy(desc(messages.createdAt))
    .limit(scope.limit ?? 50);

  return rows.reverse();
}

export interface SearchMessagesInput extends MessageScope {
  conversationIds: string[];
  query: string;
  limit?: number;
}

export async function searchConversationMessages(
  db: Database,
  input: SearchMessagesInput,
): Promise<Message[]> {
  if (input.conversationIds.length === 0) return [];

  const candidates = await db
    .select()
    .from(messages)
    .where(
      and(
        eq(messages.tenantId, input.tenantId),
        eq(messages.botId, input.botId),
        inArray(messages.conversationId, input.conversationIds),
      ),
    )
    .orderBy(desc(messages.createdAt))
    .limit(500);

  const tokens = tokenize(input.query);
  if (tokens.length === 0) {
    return candidates.slice(0, input.limit ?? 20).reverse();
  }

  const scored = candidates
    .map((message) => {
      const haystack = message.content.toLowerCase();
      let score = 0;
      for (const token of tokens) {
        if (haystack.includes(token)) score += 1;
      }
      return { message, score };
    })
    .filter((item) => item.score > 0)
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      return b.message.createdAt.getTime() - a.message.createdAt.getTime();
    });

  return scored
    .slice(0, input.limit ?? 20)
    .map((item) => item.message)
    .sort((a, b) => a.createdAt.getTime() - b.createdAt.getTime());
}

export async function listRecentMessagesForConversations(
  db: Database,
  scope: MessageScope & { conversationIds: string[]; limit?: number },
): Promise<Message[]> {
  if (scope.conversationIds.length === 0) return [];
  const rows = await db
    .select()
    .from(messages)
    .where(
      and(
        eq(messages.tenantId, scope.tenantId),
        eq(messages.botId, scope.botId),
        inArray(messages.conversationId, scope.conversationIds),
      ),
    )
    .orderBy(asc(messages.createdAt))
    .limit(scope.limit ?? 100);
  return rows;
}

const STOP_WORDS = new Set([
  "a",
  "an",
  "and",
  "are",
  "as",
  "at",
  "be",
  "by",
  "can",
  "do",
  "does",
  "for",
  "from",
  "how",
  "i",
  "in",
  "is",
  "it",
  "me",
  "my",
  "of",
  "on",
  "or",
  "our",
  "please",
  "the",
  "this",
  "to",
  "we",
  "what",
  "when",
  "where",
  "who",
  "why",
  "with",
  "you",
  "your",
]);

export function tokenize(value: string): string[] {
  return value
    .toLowerCase()
    .split(/[^a-z0-9]+/u)
    .map((token) => token.trim())
    .filter((token) => token.length > 1 && !STOP_WORDS.has(token));
}
