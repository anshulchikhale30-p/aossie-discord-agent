import { defineTool } from "eve/tools";
import { z } from "zod";
import { readScope } from "../../src/auth/scope.js";
import { listParticipantConversations } from "../../src/db/repositories/conversations.js";
import { searchConversationMessages } from "../../src/db/repositories/messages.js";
import { getDatabase } from "../../src/runtime.js";
import {
  loadInteractionCustomer,
  toIsoString,
} from "../../src/agent/tool-helpers.js";

export default defineTool({
  description:
    "Search earlier messages in the current customer's conversations. Use it to check whether a question was already answered, to recall what the customer was told before, or to avoid forwarding the same question to maintainers again. A customer can search only their own conversations. A maintainer can search the customer behind an escalation by passing interactionId; without it, the search covers the maintainer channel conversation.",
  inputSchema: z.object({
    query: z
      .string()
      .min(1)
      .describe("Words or a short phrase to look for in earlier messages."),
    interactionId: z
      .string()
      .uuid()
      .optional()
      .describe(
        "Maintainer channel only: the escalation whose customer conversation should be searched.",
      ),
    limit: z.number().int().min(1).max(50).optional(),
  }),
  async execute({ query, interactionId, limit }, ctx) {
    const scope = readScope(ctx.session.auth.current);
    const db = getDatabase();

    let conversationIds = [scope.conversationId];

    if (scope.role === "customer") {
      const conversations = await listParticipantConversations(db, {
        tenantId: scope.tenantId,
        botId: scope.botId,
        connectionId: scope.connectionId,
        participantExternalId: scope.externalUserId,
        limit: 50,
      });
      conversationIds = conversations.map((conversation) => conversation.id);
    } else if (interactionId) {
      const { subject } = await loadInteractionCustomer(
        db,
        scope,
        interactionId,
      );
      const conversations = await listParticipantConversations(db, {
        tenantId: scope.tenantId,
        botId: scope.botId,
        connectionId: subject.connectionId,
        participantExternalId: subject.externalUserId,
        limit: 50,
      });
      conversationIds = conversations.map((conversation) => conversation.id);
      if (conversationIds.length === 0) {
        return { query, searchedConversations: 0, matches: [] };
      }
    }

    const matches = await searchConversationMessages(db, {
      tenantId: scope.tenantId,
      botId: scope.botId,
      conversationIds,
      query,
      limit,
    });

    return {
      query,
      searchedConversations: conversationIds.length,
      matches: matches.map((message) => ({
        conversationId: message.conversationId,
        direction: message.direction,
        authorName: message.authorName,
        content: message.content,
        createdAt: toIsoString(message.createdAt),
      })),
    };
  },
});
