import { defineTool } from "eve/tools";
import { z } from "zod";
import { readScope } from "../../src/auth/scope.js";
import { searchKnowledge } from "../../src/db/repositories/knowledge.js";
import { getDatabase } from "../../src/runtime.js";
import {
  loadInteractionCustomer,
  toIsoString,
} from "../../src/agent/tool-helpers.js";

export default defineTool({
  description:
    "Search the provider's curated knowledge base before answering a customer question. Returns general answers that apply to every customer, plus user-specific knowledge that belongs to the current customer. Never answer a policy, pricing, eligibility, or process question from memory: search first. In the maintainer channel, pass interactionId to include the customer's user-specific knowledge.",
  inputSchema: z.object({
    query: z
      .string()
      .min(1)
      .describe(
        "The customer's question or a short keyword query that captures what you need to know.",
      ),
    interactionId: z
      .string()
      .uuid()
      .optional()
      .describe(
        "Maintainer channel only: the escalation whose customer should be searched. Omit for general knowledge only.",
      ),
    limit: z.number().int().min(1).max(20).optional(),
  }),
  async execute({ query, interactionId, limit }, ctx) {
    const scope = readScope(ctx.session.auth.current);
    const db = getDatabase();

    let connectionId = scope.connectionId;
    let externalUserId = scope.externalUserId;

    if (scope.role === "maintainer" && interactionId) {
      const { subject } = await loadInteractionCustomer(db, scope, interactionId);
      connectionId = subject.connectionId;
      externalUserId = subject.externalUserId;
    }

    const matches = await searchKnowledge(db, {
      tenantId: scope.tenantId,
      botId: scope.botId,
      connectionId,
      externalUserId,
      query,
      limit,
    });

    return {
      query,
      matches: matches.map(({ entry, score }) => ({
        id: entry.id,
        scope: entry.scope,
        title: entry.title,
        content: entry.content,
        source: entry.source,
        updatedAt: toIsoString(entry.updatedAt),
        score,
      })),
    };
  },
});
