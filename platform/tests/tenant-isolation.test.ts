import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { findConversationById, findConversationByThread } from "../src/db/repositories/conversations.js";
import { createInteraction, findInteractionById, listOpenInteractions } from "../src/db/repositories/interactions.js";
import { saveKnowledge, searchKnowledge } from "../src/db/repositories/knowledge.js";
import { findMessageByDedupeKey, recordMessage, searchConversationMessages } from "../src/db/repositories/messages.js";
import {
  createConversation,
  createTenantScope,
  createTestDatabase,
  type TenantScope,
  type TestDatabase,
} from "./helpers.js";

describe("tenant and bot isolation", () => {
  let handle: TestDatabase;
  let tenantA: TenantScope;
  let tenantB: TenantScope;

  beforeAll(async () => {
    handle = await createTestDatabase();
    tenantA = await createTenantScope(handle.db, { externalId: "discord-a" });
    tenantB = await createTenantScope(handle.db, { externalId: "discord-b" });
  });

  afterAll(async () => {
    await handle.close();
  });

  it("does not return another tenant's conversation by id or thread", async () => {
    const conversation = await createConversation(handle.db, tenantA, {
      externalThreadId: "discord:guild-1:shared-thread",
    });

    const byId = await findConversationById(handle.db, tenantB, conversation.id);
    expect(byId).toBeNull();

    const byThread = await findConversationByThread(handle.db, {
      ...tenantB,
      externalThreadId: conversation.externalThreadId,
    });
    expect(byThread).toBeNull();

    const own = await findConversationById(handle.db, tenantA, conversation.id);
    expect(own?.id).toBe(conversation.id);
  });

  it("does not leak messages or dedupe lookups across tenants", async () => {
    const conversationA = await createConversation(handle.db, tenantA);
    const conversationB = await createConversation(handle.db, tenantB);

    await recordMessage(handle.db, {
      ...tenantA,
      conversationId: conversationA.id,
      direction: "inbound",
      content: "My invoice is overdue",
      dedupeKey: "message-1",
    });

    const leakedByKey = await findMessageByDedupeKey(handle.db, {
      ...tenantB,
      conversationId: conversationA.id,
      dedupeKey: "message-1",
    });
    expect(leakedByKey).toBeNull();

    const leakedSearch = await searchConversationMessages(handle.db, {
      ...tenantB,
      conversationIds: [conversationA.id],
      query: "invoice",
    });
    expect(leakedSearch).toEqual([]);

    const ownSearch = await searchConversationMessages(handle.db, {
      ...tenantA,
      conversationIds: [conversationA.id],
      query: "invoice",
    });
    expect(ownSearch).toHaveLength(1);

    const unrelatedConversation = await findConversationById(
      handle.db,
      tenantB,
      conversationB.id,
    );
    expect(unrelatedConversation?.id).toBe(conversationB.id);
  });

  it("does not return another tenant's knowledge", async () => {
    await saveKnowledge(handle.db, {
      ...tenantA,
      scope: "general",
      title: "Refund window",
      content: "Refunds are available within 30 days.",
    });

    const leaked = await searchKnowledge(handle.db, {
      ...tenantB,
      connectionId: tenantB.connectionId,
      externalUserId: "customer-b",
      query: "refund",
    });
    expect(leaked).toEqual([]);

    const own = await searchKnowledge(handle.db, {
      ...tenantA,
      connectionId: tenantA.connectionId,
      externalUserId: "customer-a",
      query: "refund",
    });
    expect(own).toHaveLength(1);
  });

  it("does not return another tenant's interactions", async () => {
    const conversationA = await createConversation(handle.db, tenantA);
    const created = await createInteraction(handle.db, {
      ...tenantA,
      conversationId: conversationA.id,
      question: "Can I get an extension?",
      dedupeKey: "interaction-1",
      maintainerChannelId: "maintainer-channel",
    });

    const leaked = await findInteractionById(
      handle.db,
      tenantB,
      created.interaction.id,
    );
    expect(leaked).toBeNull();

    const openForB = await listOpenInteractions(handle.db, tenantB);
    expect(openForB).toEqual([]);

    const openForA = await listOpenInteractions(handle.db, tenantA);
    expect(openForA.map((row) => row.id)).toEqual([created.interaction.id]);
  });
});
