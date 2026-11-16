import { eq } from "drizzle-orm";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  findLatestInboundMessage,
  findMessageByDedupeKey,
  listConversationMessages,
  recordMessage,
  searchConversationMessages,
  updateMessageDeliveryStatus,
} from "../src/db/repositories/messages.js";
import { messages } from "../src/db/schema.js";
import {
  createConversation,
  createTenantScope,
  createTestDatabase,
  type TenantScope,
  type TestDatabase,
} from "./helpers.js";

describe("canonical message persistence", () => {
  let handle: TestDatabase;
  let tenant: TenantScope;

  beforeAll(async () => {
    handle = await createTestDatabase();
    tenant = await createTenantScope(handle.db);
  });

  afterAll(async () => {
    await handle.close();
  });

  it("deduplicates a retried inbound message", async () => {
    const conversation = await createConversation(handle.db, tenant);

    const first = await recordMessage(handle.db, {
      ...tenant,
      conversationId: conversation.id,
      externalMessageId: "platform-message-1",
      direction: "inbound",
      authorExternalId: "customer-1",
      authorName: "Customer One",
      content: "I need a refund for order 42.",
      dedupeKey: "discord:message-1",
    });
    const retried = await recordMessage(handle.db, {
      ...tenant,
      conversationId: conversation.id,
      externalMessageId: "platform-message-1",
      direction: "inbound",
      authorExternalId: "customer-1",
      authorName: "Customer One",
      content: "This should not overwrite the first copy.",
      dedupeKey: "discord:message-1",
    });

    expect(first.inserted).toBe(true);
    expect(retried.inserted).toBe(false);
    expect(retried.message.id).toBe(first.message.id);
    expect(retried.message.content).toBe("I need a refund for order 42.");

    const found = await findMessageByDedupeKey(handle.db, {
      ...tenant,
      conversationId: conversation.id,
      dedupeKey: "discord:message-1",
    });
    expect(found?.id).toBe(first.message.id);
  });

  it("finds the latest inbound message and ignores outbound messages", async () => {
    const conversation = await createConversation(handle.db, tenant);

    const older = await recordMessage(handle.db, {
      ...tenant,
      conversationId: conversation.id,
      direction: "inbound",
      content: "First question",
      dedupeKey: "inbound-1",
    });
    const newer = await recordMessage(handle.db, {
      ...tenant,
      conversationId: conversation.id,
      direction: "inbound",
      content: "Second question",
      dedupeKey: "inbound-2",
    });
    await recordMessage(handle.db, {
      ...tenant,
      conversationId: conversation.id,
      direction: "outbound",
      content: "Bot reply",
      dedupeKey: "outbound-1",
    });

    await handle.db
      .update(messages)
      .set({ createdAt: new Date("2026-01-01T00:00:00Z") })
      .where(eq(messages.id, older.message.id));
    await handle.db
      .update(messages)
      .set({ createdAt: new Date("2026-01-02T00:00:00Z") })
      .where(eq(messages.id, newer.message.id));

    const latest = await findLatestInboundMessage(handle.db, {
      ...tenant,
      conversationId: conversation.id,
    });
    expect(latest?.id).toBe(newer.message.id);
    expect(latest?.content).toBe("Second question");
  });

  it("searches only the requested conversations and returns chronological matches", async () => {
    const conversation = await createConversation(handle.db, tenant);
    const other = await createConversation(handle.db, tenant);

    const first = await recordMessage(handle.db, {
      ...tenant,
      conversationId: conversation.id,
      direction: "inbound",
      content: "Where is my invoice for March?",
      dedupeKey: "search-1",
    });
    const second = await recordMessage(handle.db, {
      ...tenant,
      conversationId: conversation.id,
      direction: "outbound",
      content: "Your March invoice is attached.",
      dedupeKey: "search-2",
    });
    await recordMessage(handle.db, {
      ...tenant,
      conversationId: other.id,
      direction: "inbound",
      content: "Unrelated invoice question in another thread.",
      dedupeKey: "search-3",
    });

    await handle.db
      .update(messages)
      .set({ createdAt: new Date("2026-02-01T00:00:00Z") })
      .where(eq(messages.id, first.message.id));
    await handle.db
      .update(messages)
      .set({ createdAt: new Date("2026-02-02T00:00:00Z") })
      .where(eq(messages.id, second.message.id));

    const matches = await searchConversationMessages(handle.db, {
      ...tenant,
      conversationIds: [conversation.id],
      query: "invoice",
    });
    expect(matches.map((message) => message.id)).toEqual([
      first.message.id,
      second.message.id,
    ]);
  });

  it("lists a conversation in chronological order and updates delivery status", async () => {
    const conversation = await createConversation(handle.db, tenant);

    const first = await recordMessage(handle.db, {
      ...tenant,
      conversationId: conversation.id,
      direction: "inbound",
      content: "Hello",
      dedupeKey: "history-1",
    });
    const second = await recordMessage(handle.db, {
      ...tenant,
      conversationId: conversation.id,
      direction: "outbound",
      content: "Hi, how can I help?",
      dedupeKey: "history-2",
      deliveryStatus: "pending",
    });

    await handle.db
      .update(messages)
      .set({ createdAt: new Date("2026-03-01T00:00:00Z") })
      .where(eq(messages.id, first.message.id));
    await handle.db
      .update(messages)
      .set({ createdAt: new Date("2026-03-01T00:01:00Z") })
      .where(eq(messages.id, second.message.id));

    const history = await listConversationMessages(handle.db, {
      ...tenant,
      conversationId: conversation.id,
    });
    expect(history.map((message) => message.id)).toEqual([
      first.message.id,
      second.message.id,
    ]);

    await updateMessageDeliveryStatus(
      handle.db,
      tenant,
      second.message.id,
      "sent",
      "platform-outbound-1",
    );

    const updated = await listConversationMessages(handle.db, {
      ...tenant,
      conversationId: conversation.id,
    });
    expect(updated[1]?.deliveryStatus).toBe("sent");
    expect(updated[1]?.externalMessageId).toBe("platform-outbound-1");
  });
});
