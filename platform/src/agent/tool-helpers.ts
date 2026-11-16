import { createHash } from "node:crypto";
import type { RequestScope } from "../auth/scope.js";
import type { Database } from "../db/client.js";
import {
  findConversationById,
} from "../db/repositories/conversations.js";
import {
  findMaintainerConnection,
  type ConnectionScope,
} from "../db/repositories/connections.js";
import {
  findInteractionById,
} from "../db/repositories/interactions.js";
import {
  findKnowledgeByExactContent,
  saveKnowledge,
} from "../db/repositories/knowledge.js";
import type {
  Connection,
  Conversation,
  Interaction,
  KnowledgeEntry,
  KnowledgeScope,
} from "../db/schema.js";

/**
 * The customer behind a maintainer escalation. Tools never accept these values
 * from the model: they come from the escalation record, which was written from
 * a verified inbound customer event.
 */
export interface CustomerSubject {
  conversationId: string;
  connectionId: string;
  externalUserId: string;
  externalThreadId: string;
  participantName: string | null;
  platform: Conversation["platform"];
}

export interface InteractionCustomer {
  interaction: Interaction;
  conversation: Conversation;
  subject: CustomerSubject;
}

export async function loadInteractionCustomer(
  db: Database,
  scope: RequestScope,
  interactionId: string,
): Promise<InteractionCustomer> {
  if (scope.role !== "maintainer") {
    throw new Error(
      "Only the provider maintainer channel can inspect or answer escalations.",
    );
  }

  const interaction = await findInteractionById(db, scope, interactionId);
  if (!interaction) {
    throw new Error(
      `No escalation with id ${interactionId} exists in this workspace. Use list_open_interactions to see the open escalations.`,
    );
  }

  const conversation = await findConversationById(
    db,
    scope,
    interaction.conversationId,
  );
  if (!conversation) {
    throw new Error(
      `Escalation ${interactionId} points to a customer conversation that no longer exists.`,
    );
  }
  if (!conversation.participantExternalId) {
    throw new Error(
      `Escalation ${interactionId} is not tied to a customer identity, so it cannot be answered or given user-specific knowledge.`,
    );
  }

  return {
    interaction,
    conversation,
    subject: {
      conversationId: conversation.id,
      connectionId: conversation.connectionId,
      externalUserId: conversation.participantExternalId,
      externalThreadId: conversation.externalThreadId,
      participantName: conversation.participantName,
      platform: conversation.platform,
    },
  };
}

export interface MaintainerDestination {
  connectionId: string;
  channelId: string;
}

/**
 * Prefer the source connection's own maintainer channel. WhatsApp has no
 * maintainer channel of its own, so it falls back to the tenant's Discord
 * connection, which is the single private maintainer queue for every surface.
 */
export async function resolveMaintainerDestination(
  db: Database,
  scope: ConnectionScope,
  sourceConnection: Connection,
): Promise<MaintainerDestination | null> {
  if (sourceConnection.maintainerChannelId) {
    return {
      connectionId: sourceConnection.id,
      channelId: sourceConnection.maintainerChannelId,
    };
  }

  const maintainerConnection = await findMaintainerConnection(db, scope);
  if (!maintainerConnection?.maintainerChannelId) return null;

  return {
    connectionId: maintainerConnection.id,
    channelId: maintainerConnection.maintainerChannelId,
  };
}

/**
 * One escalation per inbound message. If a platform does not give us a message
 * id, fall back to a stable hash of the conversation and normalized question so
 * a retried tool call does not create a second escalation.
 */
export function escalationDedupeKey(input: {
  conversationId: string;
  sourceMessageId?: string | null;
  question: string;
}): string {
  if (input.sourceMessageId) {
    return `escalation:message:${input.sourceMessageId}`;
  }
  const digest = createHash("sha256")
    .update(`${input.conversationId}:${input.question.trim().toLowerCase()}`)
    .digest("hex");
  return `escalation:question:${digest}`;
}

export interface SaveKnowledgeForScopeInput {
  knowledgeScope: KnowledgeScope;
  content: string;
  title?: string | null;
  interactionId?: string | null;
  metadata?: Record<string, unknown>;
}

export interface SaveKnowledgeForScopeResult {
  entry: KnowledgeEntry;
  created: boolean;
}

/**
 * The scope rules live here, not in the model:
 * - customers may only save user-specific knowledge about themselves;
 * - maintainers may save general knowledge, or user-specific knowledge for the
 *   customer behind an escalation they name.
 */
export async function saveKnowledgeForScope(
  db: Database,
  scope: RequestScope,
  input: SaveKnowledgeForScopeInput,
): Promise<SaveKnowledgeForScopeResult> {
  const content = input.content.trim();
  if (!content) {
    throw new Error("Knowledge content cannot be empty.");
  }

  let subjectConnectionId: string | null = null;
  let subjectExternalId: string | null = null;

  if (input.knowledgeScope === "general") {
    if (scope.role !== "maintainer") {
      throw new Error(
        "Only a provider maintainer can save general knowledge. Save a fact about this customer as user-specific knowledge instead.",
      );
    }
  } else {
    if (scope.role === "customer") {
      subjectConnectionId = scope.connectionId;
      subjectExternalId = scope.externalUserId;
    } else {
      if (!input.interactionId) {
        throw new Error(
          "A maintainer must provide interactionId when saving user-specific knowledge so the knowledge is attached to the right customer.",
        );
      }
      const { subject } = await loadInteractionCustomer(
        db,
        scope,
        input.interactionId,
      );
      subjectConnectionId = subject.connectionId;
      subjectExternalId = subject.externalUserId;
    }
  }

  const existing = await findKnowledgeByExactContent(db, {
    tenantId: scope.tenantId,
    botId: scope.botId,
    content,
    knowledgeScope: input.knowledgeScope,
    subjectConnectionId,
    subjectExternalId,
  });
  if (existing) {
    return { entry: existing, created: false };
  }

  const entry = await saveKnowledge(db, {
    tenantId: scope.tenantId,
    botId: scope.botId,
    scope: input.knowledgeScope,
    subjectConnectionId,
    subjectExternalId,
    title: input.title ?? null,
    content,
    source: scope.role === "maintainer" ? "maintainer" : "customer",
    metadata: {
      ...input.metadata,
      savedByRole: scope.role,
      savedByExternalId: scope.externalUserId,
      ...(input.interactionId
        ? { sourceInteractionId: input.interactionId }
        : {}),
    },
  });

  return { entry, created: true };
}

export function toIsoString(value: Date | null | undefined): string | null {
  return value ? value.toISOString() : null;
}
