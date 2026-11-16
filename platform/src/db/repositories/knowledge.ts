import { randomUUID } from "node:crypto";
import {
  and,
  desc,
  eq,
  gt,
  isNull,
  lte,
  or,
} from "drizzle-orm";
import type { Database } from "../client.js";
import {
  knowledgeEntries,
  type KnowledgeEntry,
  type KnowledgeScope,
  type KnowledgeStatus,
} from "../schema.js";
import { tokenize } from "./messages.js";

export interface KnowledgeScopeColumns {
  tenantId: string;
  botId: string;
}

export interface SearchKnowledgeInput extends KnowledgeScopeColumns {
  connectionId: string;
  externalUserId: string;
  query: string;
  limit?: number;
}

export interface KnowledgeMatch {
  entry: KnowledgeEntry;
  score: number;
}

function scoreEntry(
  entry: KnowledgeEntry,
  query: string,
  tokens: string[],
): number {
  const title = (entry.title ?? "").toLowerCase();
  const content = entry.content.toLowerCase();
  const normalizedQuery = query.trim().toLowerCase();

  let score = 0;
  if (normalizedQuery.length > 0) {
    if (title === normalizedQuery) score += 8;
    if (title.includes(normalizedQuery)) score += 4;
    if (content.includes(normalizedQuery)) score += 6;
  }

  for (const token of tokens) {
    if (title.includes(token)) score += 2;
    if (content.includes(token)) score += 1;
  }

  if (entry.scope === "user") score += 0.5;
  return score;
}

/**
 * Provider knowledge is intentionally small and curated. Rank in application
 * code so the same query works on every PostgreSQL-compatible engine and the
 * MVP does not require a vector extension.
 */
export async function searchKnowledge(
  db: Database,
  input: SearchKnowledgeInput,
): Promise<KnowledgeMatch[]> {
  const now = new Date();
  const rows = await db
    .select()
    .from(knowledgeEntries)
    .where(
      and(
        eq(knowledgeEntries.tenantId, input.tenantId),
        eq(knowledgeEntries.botId, input.botId),
        eq(knowledgeEntries.status, "active"),
        or(
          isNull(knowledgeEntries.effectiveAt),
          lte(knowledgeEntries.effectiveAt, now),
        ),
        or(
          isNull(knowledgeEntries.expiresAt),
          gt(knowledgeEntries.expiresAt, now),
        ),
        or(
          eq(knowledgeEntries.scope, "general"),
          and(
            eq(knowledgeEntries.scope, "user"),
            eq(knowledgeEntries.subjectConnectionId, input.connectionId),
            eq(knowledgeEntries.subjectExternalId, input.externalUserId),
          ),
        ),
      ),
    )
    .orderBy(desc(knowledgeEntries.updatedAt))
    .limit(200);

  const tokens = tokenize(input.query);
  const query = input.query.trim();

  if (tokens.length === 0 && query.length === 0) {
    return rows.slice(0, input.limit ?? 8).map((entry) => ({ entry, score: 0 }));
  }

  return rows
    .map((entry) => ({ entry, score: scoreEntry(entry, query, tokens) }))
    .filter((match) => match.score > 0)
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      return b.entry.updatedAt.getTime() - a.entry.updatedAt.getTime();
    })
    .slice(0, input.limit ?? 8);
}

export interface SaveKnowledgeInput extends KnowledgeScopeColumns {
  scope: KnowledgeScope;
  subjectConnectionId?: string | null;
  subjectExternalId?: string | null;
  title?: string | null;
  content: string;
  source?: string;
  status?: KnowledgeStatus;
  effectiveAt?: Date | null;
  expiresAt?: Date | null;
  metadata?: Record<string, unknown>;
}

export async function saveKnowledge(
  db: Database,
  input: SaveKnowledgeInput,
): Promise<KnowledgeEntry> {
  if (input.scope === "user") {
    if (!input.subjectConnectionId || !input.subjectExternalId) {
      throw new Error(
        "User-specific knowledge requires a connection and external user id.",
      );
    }
  }

  const inserted = await db
    .insert(knowledgeEntries)
    .values({
      id: randomUUID(),
      tenantId: input.tenantId,
      botId: input.botId,
      scope: input.scope,
      subjectConnectionId:
        input.scope === "user" ? input.subjectConnectionId : null,
      subjectExternalId:
        input.scope === "user" ? input.subjectExternalId : null,
      title: input.title ?? null,
      content: input.content,
      source: input.source ?? "provider",
      status: input.status ?? "active",
      effectiveAt: input.effectiveAt ?? null,
      expiresAt: input.expiresAt ?? null,
      metadata: input.metadata ?? {},
    })
    .returning();
  return inserted[0]!;
}

export async function findKnowledgeByExactContent(
  db: Database,
  scope: KnowledgeScopeColumns & {
    content: string;
    knowledgeScope: KnowledgeScope;
    subjectConnectionId?: string | null;
    subjectExternalId?: string | null;
  },
): Promise<KnowledgeEntry | null> {
  const conditions = [
    eq(knowledgeEntries.tenantId, scope.tenantId),
    eq(knowledgeEntries.botId, scope.botId),
    eq(knowledgeEntries.scope, scope.knowledgeScope),
    eq(knowledgeEntries.content, scope.content),
    eq(knowledgeEntries.status, "active"),
  ];
  if (scope.knowledgeScope === "user") {
    conditions.push(
      eq(knowledgeEntries.subjectConnectionId, scope.subjectConnectionId ?? ""),
      eq(knowledgeEntries.subjectExternalId, scope.subjectExternalId ?? ""),
    );
  }

  const rows = await db
    .select()
    .from(knowledgeEntries)
    .where(and(...conditions))
    .limit(1);
  return rows[0] ?? null;
}

export async function findKnowledgeEntryById(
  db: Database,
  scope: KnowledgeScopeColumns,
  entryId: string,
): Promise<KnowledgeEntry | null> {
  const rows = await db
    .select()
    .from(knowledgeEntries)
    .where(
      and(
        eq(knowledgeEntries.tenantId, scope.tenantId),
        eq(knowledgeEntries.botId, scope.botId),
        eq(knowledgeEntries.id, entryId),
      ),
    )
    .limit(1);
  return rows[0] ?? null;
}

export async function listKnowledge(
  db: Database,
  scope: KnowledgeScopeColumns & {
    scope?: KnowledgeScope;
    status?: KnowledgeStatus;
    limit?: number;
  },
): Promise<KnowledgeEntry[]> {
  const conditions = [
    eq(knowledgeEntries.tenantId, scope.tenantId),
    eq(knowledgeEntries.botId, scope.botId),
  ];
  if (scope.scope) {
    conditions.push(eq(knowledgeEntries.scope, scope.scope));
  }
  if (scope.status) {
    conditions.push(eq(knowledgeEntries.status, scope.status));
  }

  return db
    .select()
    .from(knowledgeEntries)
    .where(and(...conditions))
    .orderBy(desc(knowledgeEntries.updatedAt))
    .limit(scope.limit ?? 100);
}

export async function supersedeKnowledge(
  db: Database,
  scope: KnowledgeScopeColumns,
  entryId: string,
): Promise<KnowledgeEntry | null> {
  const rows = await db
    .update(knowledgeEntries)
    .set({ status: "superseded", updatedAt: new Date() })
    .where(
      and(
        eq(knowledgeEntries.tenantId, scope.tenantId),
        eq(knowledgeEntries.botId, scope.botId),
        eq(knowledgeEntries.id, entryId),
      ),
    )
    .returning();
  return rows[0] ?? null;
}
