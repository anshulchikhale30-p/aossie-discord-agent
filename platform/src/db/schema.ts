import {
  index,
  jsonb,
  pgTable,
  text,
  timestamp,
  uniqueIndex,
  uuid,
} from "drizzle-orm/pg-core";

export type Platform = "discord" | "whatsapp";
export type ConversationKind = "dm" | "group" | "maintainer";
export type MessageDirection = "inbound" | "outbound";
export type DeliveryStatus = "pending" | "sent" | "failed";
export type KnowledgeScope = "general" | "user";
export type KnowledgeStatus = "active" | "expired" | "cancelled" | "superseded";
export type InteractionStatus =
  | "open"
  | "waiting_for_maintainer"
  | "response_received"
  | "resolved"
  | "cancelled";
export type InteractionPriority = "low" | "normal" | "high" | "urgent";
export type ActorType = "customer" | "maintainer" | "system";

const timestamps = {
  createdAt: timestamp("created_at", { withTimezone: true, mode: "date" })
    .notNull()
    .defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true, mode: "date" })
    .notNull()
    .defaultNow(),
};

export const tenants = pgTable("tenants", {
  id: uuid("id").primaryKey(),
  slug: text("slug").notNull().unique(),
  name: text("name").notNull(),
  metadata: jsonb("metadata")
    .$type<Record<string, unknown>>()
    .notNull()
    .default({}),
  ...timestamps,
});

export const bots = pgTable(
  "bots",
  {
    id: uuid("id").primaryKey(),
    tenantId: uuid("tenant_id")
      .notNull()
      .references(() => tenants.id, { onDelete: "cascade" }),
    slug: text("slug").notNull(),
    name: text("name").notNull(),
    /**
     * Provider-authored system instructions managed by the dashboard. The
     * static safety rules live in agent/instructions.md; this value is appended
     * by the dynamic instruction module.
     */
    systemPrompt: text("system_prompt"),
    metadata: jsonb("metadata")
      .$type<Record<string, unknown>>()
      .notNull()
      .default({}),
    ...timestamps,
  },
  (table) => [
    uniqueIndex("bots_tenant_slug_idx").on(table.tenantId, table.slug),
  ],
);

export const connections = pgTable(
  "connections",
  {
    id: uuid("id").primaryKey(),
    tenantId: uuid("tenant_id")
      .notNull()
      .references(() => tenants.id, { onDelete: "cascade" }),
    botId: uuid("bot_id")
      .notNull()
      .references(() => bots.id, { onDelete: "cascade" }),
    platform: text("platform").$type<Platform>().notNull(),
    /**
     * Provider-owned identity: the Discord application ID or the WhatsApp
     * phone number ID. Never the SaaS identity.
     */
    externalId: text("external_id").notNull(),
    displayName: text("display_name").notNull(),
    /**
     * Full Chat SDK channel id used for provider-facing escalations, such as
     * `discord:1234567890`. Only Discord currently has a maintainer channel.
     */
    maintainerChannelId: text("maintainer_channel_id"),
    status: text("status").notNull().default("active"),
    capabilities: jsonb("capabilities")
      .$type<Record<string, unknown>>()
      .notNull()
      .default({}),
    metadata: jsonb("metadata")
      .$type<Record<string, unknown>>()
      .notNull()
      .default({}),
    ...timestamps,
  },
  (table) => [
    uniqueIndex("connections_identity_idx").on(
      table.tenantId,
      table.botId,
      table.platform,
      table.externalId,
    ),
    index("connections_tenant_bot_idx").on(table.tenantId, table.botId),
  ],
);

export const conversations = pgTable(
  "conversations",
  {
    id: uuid("id").primaryKey(),
    tenantId: uuid("tenant_id")
      .notNull()
      .references(() => tenants.id, { onDelete: "cascade" }),
    botId: uuid("bot_id")
      .notNull()
      .references(() => bots.id, { onDelete: "cascade" }),
    connectionId: uuid("connection_id")
      .notNull()
      .references(() => connections.id, { onDelete: "cascade" }),
    platform: text("platform").$type<Platform>().notNull(),
    /** Full Chat SDK thread id, for example `discord:guild:channel`. */
    externalThreadId: text("external_thread_id").notNull(),
    /** Chat SDK channel id, used to detect the maintainer channel. */
    externalChannelId: text("external_channel_id").notNull(),
    kind: text("kind").$type<ConversationKind>().notNull(),
    title: text("title"),
    participantExternalId: text("participant_external_id"),
    participantName: text("participant_name"),
    status: text("status").notNull().default("active"),
    metadata: jsonb("metadata")
      .$type<Record<string, unknown>>()
      .notNull()
      .default({}),
    ...timestamps,
  },
  (table) => [
    uniqueIndex("conversations_thread_idx").on(
      table.connectionId,
      table.externalThreadId,
    ),
    index("conversations_tenant_bot_idx").on(table.tenantId, table.botId),
    index("conversations_participant_idx").on(
      table.tenantId,
      table.botId,
      table.participantExternalId,
    ),
  ],
);

export const messages = pgTable(
  "messages",
  {
    id: uuid("id").primaryKey(),
    tenantId: uuid("tenant_id")
      .notNull()
      .references(() => tenants.id, { onDelete: "cascade" }),
    botId: uuid("bot_id")
      .notNull()
      .references(() => bots.id, { onDelete: "cascade" }),
    conversationId: uuid("conversation_id")
      .notNull()
      .references(() => conversations.id, { onDelete: "cascade" }),
    externalMessageId: text("external_message_id"),
    direction: text("direction").$type<MessageDirection>().notNull(),
    authorExternalId: text("author_external_id"),
    authorName: text("author_name"),
    content: text("content").notNull(),
    contentJson: jsonb("content_json").$type<Record<string, unknown>>(),
    /**
     * Stable per-conversation idempotency key. Inbound: the platform message
     * id. Outbound: the eve session id plus the content part id.
     */
    dedupeKey: text("dedupe_key").notNull(),
    deliveryStatus: text("delivery_status")
      .$type<DeliveryStatus>()
      .notNull()
      .default("sent"),
    metadata: jsonb("metadata")
      .$type<Record<string, unknown>>()
      .notNull()
      .default({}),
    ...timestamps,
  },
  (table) => [
    uniqueIndex("messages_dedupe_idx").on(
      table.conversationId,
      table.dedupeKey,
    ),
    index("messages_conversation_created_idx").on(
      table.conversationId,
      table.createdAt,
    ),
    index("messages_tenant_bot_idx").on(table.tenantId, table.botId),
  ],
);

export const knowledgeEntries = pgTable(
  "knowledge_entries",
  {
    id: uuid("id").primaryKey(),
    tenantId: uuid("tenant_id")
      .notNull()
      .references(() => tenants.id, { onDelete: "cascade" }),
    botId: uuid("bot_id")
      .notNull()
      .references(() => bots.id, { onDelete: "cascade" }),
    scope: text("scope").$type<KnowledgeScope>().notNull(),
    /**
     * User-specific knowledge is keyed by the connection plus the external
     * user id. A matching name or phone number on another connection is not
     * sufficient to merge identities.
     */
    subjectConnectionId: uuid("subject_connection_id").references(
      () => connections.id,
      { onDelete: "cascade" },
    ),
    subjectExternalId: text("subject_external_id"),
    title: text("title"),
    content: text("content").notNull(),
    source: text("source").notNull().default("provider"),
    status: text("status").$type<KnowledgeStatus>().notNull().default("active"),
    effectiveAt: timestamp("effective_at", {
      withTimezone: true,
      mode: "date",
    }),
    expiresAt: timestamp("expires_at", { withTimezone: true, mode: "date" }),
    metadata: jsonb("metadata")
      .$type<Record<string, unknown>>()
      .notNull()
      .default({}),
    ...timestamps,
  },
  (table) => [
    index("knowledge_scope_idx").on(
      table.tenantId,
      table.botId,
      table.scope,
      table.status,
    ),
    index("knowledge_subject_idx").on(
      table.tenantId,
      table.botId,
      table.subjectConnectionId,
      table.subjectExternalId,
    ),
  ],
);

export const interactions = pgTable(
  "interactions",
  {
    id: uuid("id").primaryKey(),
    tenantId: uuid("tenant_id")
      .notNull()
      .references(() => tenants.id, { onDelete: "cascade" }),
    botId: uuid("bot_id")
      .notNull()
      .references(() => bots.id, { onDelete: "cascade" }),
    conversationId: uuid("conversation_id")
      .notNull()
      .references(() => conversations.id, { onDelete: "cascade" }),
    sourceMessageId: uuid("source_message_id").references(() => messages.id, {
      onDelete: "set null",
    }),
    question: text("question").notNull(),
    context: text("context"),
    status: text("status")
      .$type<InteractionStatus>()
      .notNull()
      .default("open"),
    priority: text("priority")
      .$type<InteractionPriority>()
      .notNull()
      .default("normal"),
    dedupeKey: text("dedupe_key").notNull(),
    maintainerConnectionId: uuid("maintainer_connection_id").references(
      () => connections.id,
      { onDelete: "set null" },
    ),
    maintainerChannelId: text("maintainer_channel_id"),
    maintainerThreadId: text("maintainer_thread_id"),
    maintainerMessageId: text("maintainer_message_id"),
    responseText: text("response_text"),
    respondedByExternalId: text("responded_by_external_id"),
    respondedAt: timestamp("responded_at", {
      withTimezone: true,
      mode: "date",
    }),
    resolvedAt: timestamp("resolved_at", {
      withTimezone: true,
      mode: "date",
    }),
    metadata: jsonb("metadata")
      .$type<Record<string, unknown>>()
      .notNull()
      .default({}),
    ...timestamps,
  },
  (table) => [
    uniqueIndex("interactions_dedupe_idx").on(
      table.tenantId,
      table.botId,
      table.dedupeKey,
    ),
    index("interactions_open_idx").on(
      table.tenantId,
      table.botId,
      table.status,
      table.createdAt,
    ),
    index("interactions_conversation_idx").on(table.conversationId),
  ],
);

export const auditEvents = pgTable(
  "audit_events",
  {
    id: uuid("id").primaryKey(),
    tenantId: uuid("tenant_id")
      .notNull()
      .references(() => tenants.id, { onDelete: "cascade" }),
    botId: uuid("bot_id")
      .notNull()
      .references(() => bots.id, { onDelete: "cascade" }),
    actorType: text("actor_type").$type<ActorType>().notNull(),
    actorExternalId: text("actor_external_id"),
    action: text("action").notNull(),
    subjectType: text("subject_type"),
    subjectId: text("subject_id"),
    data: jsonb("data")
      .$type<Record<string, unknown>>()
      .notNull()
      .default({}),
    createdAt: timestamp("created_at", { withTimezone: true, mode: "date" })
      .notNull()
      .defaultNow(),
  },
  (table) => [
    index("audit_tenant_bot_created_idx").on(
      table.tenantId,
      table.botId,
      table.createdAt,
    ),
  ],
);

export type Tenant = typeof tenants.$inferSelect;
export type Bot = typeof bots.$inferSelect;
export type Connection = typeof connections.$inferSelect;
export type Conversation = typeof conversations.$inferSelect;
export type Message = typeof messages.$inferSelect;
export type KnowledgeEntry = typeof knowledgeEntries.$inferSelect;
export type Interaction = typeof interactions.$inferSelect;
export type AuditEvent = typeof auditEvents.$inferSelect;
