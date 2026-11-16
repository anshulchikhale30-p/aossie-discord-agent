import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { saveKnowledgeForScope } from "../src/agent/tool-helpers.js";
import {
  saveKnowledge,
  searchKnowledge,
} from "../src/db/repositories/knowledge.js";
import { createInteraction } from "../src/db/repositories/interactions.js";
import { connections } from "../src/db/schema.js";
import {
  createConversation,
  createTenantScope,
  createTestDatabase,
  scopeFor,
  type TenantScope,
  type TestDatabase,
} from "./helpers.js";

describe("knowledge scoping", () => {
  let handle: TestDatabase;
  let tenant: TenantScope;

  beforeAll(async () => {
    handle = await createTestDatabase();
    tenant = await createTenantScope(handle.db, { externalId: "discord-app" });
  });

  afterAll(async () => {
    await handle.close();
  });

  it("returns general knowledge to every customer", async () => {
    await saveKnowledge(handle.db, {
      ...tenant,
      scope: "general",
      title: "Support hours",
      content: "Support is available Monday through Friday, 9am to 5pm IST.",
    });

    const first = await searchKnowledge(handle.db, {
      ...tenant,
      connectionId: tenant.connectionId,
      externalUserId: "customer-1",
      query: "support hours",
    });
    const second = await searchKnowledge(handle.db, {
      ...tenant,
      connectionId: tenant.connectionId,
      externalUserId: "customer-2",
      query: "support hours",
    });

    expect(first.map((match) => match.entry.title)).toContain("Support hours");
    expect(second.map((match) => match.entry.title)).toContain("Support hours");
  });

  it("returns user-specific knowledge only to the matching customer", async () => {
    await saveKnowledge(handle.db, {
      ...tenant,
      scope: "user",
      subjectConnectionId: tenant.connectionId,
      subjectExternalId: "customer-1",
      title: "Plan",
      content: "Customer one is on the enterprise plan with priority support.",
    });

    const owner = await searchKnowledge(handle.db, {
      ...tenant,
      connectionId: tenant.connectionId,
      externalUserId: "customer-1",
      query: "enterprise plan",
    });
    expect(owner.map((match) => match.entry.title)).toContain("Plan");

    const otherCustomer = await searchKnowledge(handle.db, {
      ...tenant,
      connectionId: tenant.connectionId,
      externalUserId: "customer-2",
      query: "enterprise plan",
    });
    expect(otherCustomer.map((match) => match.entry.title)).not.toContain("Plan");
  });

  it("does not merge identities across connections with the same external id", async () => {
    const secondConnectionId = randomUUID();
    await handle.db.insert(connections).values({
      id: secondConnectionId,
      tenantId: tenant.tenantId,
      botId: tenant.botId,
      platform: "whatsapp",
      externalId: "whatsapp-phone",
      displayName: "WhatsApp test",
    });

    await saveKnowledge(handle.db, {
      ...tenant,
      scope: "user",
      subjectConnectionId: secondConnectionId,
      subjectExternalId: "customer-1",
      title: "WhatsApp-only note",
      content: "Customer one asked for WhatsApp delivery on this channel.",
    });

    const viaDiscord = await searchKnowledge(handle.db, {
      ...tenant,
      connectionId: tenant.connectionId,
      externalUserId: "customer-1",
      query: "WhatsApp delivery",
    });
    expect(viaDiscord.map((match) => match.entry.title)).not.toContain(
      "WhatsApp-only note",
    );

    const viaWhatsApp = await searchKnowledge(handle.db, {
      ...tenant,
      connectionId: secondConnectionId,
      externalUserId: "customer-1",
      query: "WhatsApp delivery",
    });
    expect(viaWhatsApp.map((match) => match.entry.title)).toContain(
      "WhatsApp-only note",
    );
  });

  it("ignores expired and not-yet-effective knowledge", async () => {
    await saveKnowledge(handle.db, {
      ...tenant,
      scope: "general",
      title: "Old promotion",
      content: "The winter promotion ended.",
      expiresAt: new Date(Date.now() - 60_000),
    });
    await saveKnowledge(handle.db, {
      ...tenant,
      scope: "general",
      title: "Future promotion",
      content: "The summer promotion starts next month.",
      effectiveAt: new Date(Date.now() + 60_000),
    });

    const matches = await searchKnowledge(handle.db, {
      ...tenant,
      connectionId: tenant.connectionId,
      externalUserId: "customer-1",
      query: "promotion",
    });
    const titles = matches.map((match) => match.entry.title);
    expect(titles).not.toContain("Old promotion");
    expect(titles).not.toContain("Future promotion");
  });

  it("lets a customer save user-specific knowledge about themselves only", async () => {
    const conversation = await createConversation(handle.db, tenant, {
      participantExternalId: "customer-1",
    });
    const customerScope = scopeFor(tenant, conversation, "customer");

    await expect(
      saveKnowledgeForScope(handle.db, customerScope, {
        knowledgeScope: "general",
        content: "All customers get a 90 day refund window.",
      }),
    ).rejects.toThrow(/maintainer/i);

    const saved = await saveKnowledgeForScope(handle.db, customerScope, {
      knowledgeScope: "user",
      content: "Customer one uses the handle @customer-one on Discord.",
    });
    expect(saved.created).toBe(true);
    expect(saved.entry.subjectConnectionId).toBe(tenant.connectionId);
    expect(saved.entry.subjectExternalId).toBe("customer-1");

    const duplicate = await saveKnowledgeForScope(handle.db, customerScope, {
      knowledgeScope: "user",
      content: "Customer one uses the handle @customer-one on Discord.",
    });
    expect(duplicate.created).toBe(false);
    expect(duplicate.entry.id).toBe(saved.entry.id);
  });

  it("requires an escalation when a maintainer saves user-specific knowledge", async () => {
    const conversation = await createConversation(handle.db, tenant, {
      participantExternalId: "customer-9",
      participantName: "Customer Nine",
    });
    const maintainerConversation = await createConversation(handle.db, tenant, {
      externalThreadId: "discord:guild-1:maintainer-channel",
      participantExternalId: "maintainer-1",
      kind: "maintainer",
    });
    const maintainerScope = scopeFor(
      tenant,
      maintainerConversation,
      "maintainer",
    );

    const general = await saveKnowledgeForScope(handle.db, maintainerScope, {
      knowledgeScope: "general",
      content: "All invoices are issued on the first of the month.",
    });
    expect(general.created).toBe(true);

    await expect(
      saveKnowledgeForScope(handle.db, maintainerScope, {
        knowledgeScope: "user",
        content: "Customer nine has a custom billing date.",
      }),
    ).rejects.toThrow(/interactionId/i);

    const escalation = await createInteraction(handle.db, {
      ...tenant,
      conversationId: conversation.id,
      question: "Can my billing date change?",
      dedupeKey: `escalation-${conversation.id}`,
      maintainerChannelId: "maintainer-channel",
    });

    const userKnowledge = await saveKnowledgeForScope(
      handle.db,
      maintainerScope,
      {
        knowledgeScope: "user",
        content: "Customer nine has a custom billing date.",
        interactionId: escalation.interaction.id,
      },
    );

    expect(userKnowledge.created).toBe(true);
    expect(userKnowledge.entry.subjectConnectionId).toBe(tenant.connectionId);
    expect(userKnowledge.entry.subjectExternalId).toBe("customer-9");

    const customerMatches = await searchKnowledge(handle.db, {
      ...tenant,
      connectionId: tenant.connectionId,
      externalUserId: "customer-9",
      query: "billing date",
    });
    expect(customerMatches.map((match) => match.entry.content)).toContain(
      "Customer nine has a custom billing date.",
    );
  });
});
