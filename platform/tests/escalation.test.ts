import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  escalationDedupeKey,
  loadInteractionCustomer,
  resolveMaintainerDestination,
} from "../src/agent/tool-helpers.js";
import { findConnectionById } from "../src/db/repositories/connections.js";
import { connections } from "../src/db/schema.js";
import {
  createInteraction,
  findInteractionByDedupeKey,
  findInteractionByMaintainerMessageId,
  findInteractionByMaintainerThreadId,
  findLatestOpenInteractionForChannel,
  listOpenInteractions,
  recordInteractionAnswer,
  resolveInteraction,
  setInteractionNotification,
} from "../src/db/repositories/interactions.js";
import {
  createConversation,
  createTenantScope,
  createTestDatabase,
  scopeFor,
  type TenantScope,
  type TestDatabase,
} from "./helpers.js";

describe("escalation lifecycle", () => {
  let handle: TestDatabase;
  let tenant: TenantScope;

  beforeAll(async () => {
    handle = await createTestDatabase();
    tenant = await createTenantScope(handle.db, {
      maintainerChannelId: "maintainer-channel",
    });
  });

  afterAll(async () => {
    await handle.close();
  });

  it("deduplicates an escalation by dedupe key", async () => {
    const conversation = await createConversation(handle.db, tenant);
    const input = {
      ...tenant,
      conversationId: conversation.id,
      question: "Can I change my plan?",
      dedupeKey: `escalation:${conversation.id}`,
      maintainerChannelId: "maintainer-channel",
    };

    const first = await createInteraction(handle.db, input);
    const second = await createInteraction(handle.db, {
      ...input,
      question: "Can I change my plan today?",
    });

    expect(first.inserted).toBe(true);
    expect(second.inserted).toBe(false);
    expect(second.interaction.id).toBe(first.interaction.id);
    expect(second.interaction.question).toBe("Can I change my plan?");

    const found = await findInteractionByDedupeKey(handle.db, {
      ...tenant,
      dedupeKey: input.dedupeKey,
    });
    expect(found?.id).toBe(first.interaction.id);
  });

  it("tracks the maintainer notification and open state", async () => {
    const conversation = await createConversation(handle.db, tenant);
    const created = await createInteraction(handle.db, {
      ...tenant,
      conversationId: conversation.id,
      question: "Please refund order 42.",
      dedupeKey: `escalation:${conversation.id}`,
      maintainerChannelId: "maintainer-channel",
    });

    const notified = await setInteractionNotification(
      handle.db,
      tenant,
      created.interaction.id,
      {
        maintainerConnectionId: tenant.connectionId,
        maintainerChannelId: "maintainer-channel",
        maintainerThreadId: "discord:guild-1:maintainer-channel",
        maintainerMessageId: "maintainer-message-42",
      },
    );
    expect(notified?.status).toBe("waiting_for_maintainer");

    const byThread = await findInteractionByMaintainerThreadId(
      handle.db,
      tenant,
      "discord:guild-1:maintainer-channel",
    );
    expect(byThread?.id).toBe(created.interaction.id);

    const byMessage = await findInteractionByMaintainerMessageId(
      handle.db,
      tenant,
      "maintainer-message-42",
    );
    expect(byMessage?.id).toBe(created.interaction.id);

    const open = await listOpenInteractions(handle.db, {
      ...tenant,
      maintainerChannelId: "maintainer-channel",
    });
    expect(open.map((row) => row.id)).toContain(created.interaction.id);

    const otherChannel = await listOpenInteractions(handle.db, {
      ...tenant,
      maintainerChannelId: "another-channel",
    });
    expect(otherChannel.map((row) => row.id)).not.toContain(
      created.interaction.id,
    );

    const latest = await findLatestOpenInteractionForChannel(handle.db, {
      ...tenant,
      maintainerChannelId: "maintainer-channel",
    });
    expect(latest?.id).toBe(created.interaction.id);
  });

  it("records the maintainer answer and closes the escalation", async () => {
    const conversation = await createConversation(handle.db, tenant);
    const created = await createInteraction(handle.db, {
      ...tenant,
      conversationId: conversation.id,
      question: "Where is my order?",
      dedupeKey: `escalation:${conversation.id}`,
      maintainerChannelId: "maintainer-channel",
    });
    const threadId = `discord:guild-1:thread-${conversation.id}`;
    await setInteractionNotification(handle.db, tenant, created.interaction.id, {
      maintainerConnectionId: tenant.connectionId,
      maintainerChannelId: "maintainer-channel",
      maintainerThreadId: threadId,
      maintainerMessageId: `message-${conversation.id}`,
    });

    const answered = await recordInteractionAnswer(
      handle.db,
      tenant,
      created.interaction.id,
      {
        responseText: "Your order ships tomorrow.",
        respondedByExternalId: "maintainer-1",
      },
    );
    expect(answered?.status).toBe("response_received");
    expect(answered?.responseText).toBe("Your order ships tomorrow.");
    expect(answered?.respondedAt).toBeInstanceOf(Date);

    const resolved = await resolveInteraction(
      handle.db,
      tenant,
      created.interaction.id,
    );
    expect(resolved?.status).toBe("resolved");
    expect(resolved?.resolvedAt).toBeInstanceOf(Date);

    const byThread = await findInteractionByMaintainerThreadId(
      handle.db,
      tenant,
      threadId,
    );
    expect(byThread).toBeNull();

    const open = await listOpenInteractions(handle.db, tenant);
    expect(open.map((row) => row.id)).not.toContain(created.interaction.id);
  });

  it("resolves the customer behind an escalation only for maintainers", async () => {
    const conversation = await createConversation(handle.db, tenant, {
      participantExternalId: "customer-42",
      participantName: "Ada",
    });
    const created = await createInteraction(handle.db, {
      ...tenant,
      conversationId: conversation.id,
      question: "Is my account active?",
      dedupeKey: `escalation:${conversation.id}`,
      maintainerChannelId: "maintainer-channel",
    });

    const customerScope = scopeFor(tenant, conversation, "customer");
    await expect(
      loadInteractionCustomer(handle.db, customerScope, created.interaction.id),
    ).rejects.toThrow(/maintainer/i);

    const maintainerScope = scopeFor(tenant, conversation, "maintainer");
    const loaded = await loadInteractionCustomer(
      handle.db,
      maintainerScope,
      created.interaction.id,
    );
    expect(loaded.subject.externalUserId).toBe("customer-42");
    expect(loaded.subject.participantName).toBe("Ada");
    expect(loaded.subject.conversationId).toBe(conversation.id);

    await expect(
      loadInteractionCustomer(handle.db, maintainerScope, randomUUID()),
    ).rejects.toThrow(/No escalation/i);
  });

  it("routes a WhatsApp escalation to the Discord maintainer channel", async () => {
    const whatsappConnectionId = randomUUID();
    await handle.db.insert(connections).values({
      id: whatsappConnectionId,
      tenantId: tenant.tenantId,
      botId: tenant.botId,
      platform: "whatsapp",
      externalId: "whatsapp-phone",
      displayName: "WhatsApp test",
    });

    const discordConnection = await findConnectionById(
      handle.db,
      tenant,
      tenant.connectionId,
    );
    const whatsappConnection = await findConnectionById(
      handle.db,
      tenant,
      whatsappConnectionId,
    );
    expect(discordConnection?.maintainerChannelId).toBe("maintainer-channel");
    expect(whatsappConnection?.maintainerChannelId).toBeNull();

    const whatsappScope = {
      tenantId: tenant.tenantId,
      botId: tenant.botId,
    };

    await expect(
      resolveMaintainerDestination(
        handle.db,
        whatsappScope,
        whatsappConnection!,
      ),
    ).resolves.toEqual({
      connectionId: tenant.connectionId,
      channelId: "maintainer-channel",
    });

    await expect(
      resolveMaintainerDestination(handle.db, tenant, discordConnection!),
    ).resolves.toEqual({
      connectionId: tenant.connectionId,
      channelId: "maintainer-channel",
    });
  });

  it("builds a stable dedupe key from a source message or question", () => {
    const byMessage = escalationDedupeKey({
      conversationId: "conversation-1",
      sourceMessageId: "message-1",
      question: "One",
    });
    expect(byMessage).toBe("escalation:message:message-1");
    expect(
      escalationDedupeKey({
        conversationId: "conversation-1",
        sourceMessageId: "message-1",
        question: "Different wording",
      }),
    ).toBe(byMessage);

    const byQuestion = escalationDedupeKey({
      conversationId: "conversation-1",
      question: "  Where is my order? ",
    });
    expect(byQuestion).toBe(
      escalationDedupeKey({
        conversationId: "conversation-1",
        question: "where is my order?",
      }),
    );
    expect(
      escalationDedupeKey({
        conversationId: "conversation-2",
        question: "Where is my order?",
      }),
    ).not.toBe(byQuestion);
  });
});
