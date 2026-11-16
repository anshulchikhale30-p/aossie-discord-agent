import { defineTool } from "eve/tools";
import { z } from "zod";
import { readScope } from "../../src/auth/scope.js";
import { getDatabase } from "../../src/runtime.js";
import {
  saveKnowledgeForScope,
  toIsoString,
} from "../../src/agent/tool-helpers.js";

export default defineTool({
  description:
    "Store a durable answer or fact in the provider's knowledge base so it can be reused later. General knowledge is true for every customer and only a maintainer may save it. User-specific knowledge belongs to one customer: a customer may save a fact about themselves, and a maintainer must pass the interactionId of that customer's escalation. Do not save guesses, one-off chat, secrets, or information from outside the provider's channel. If the exact content already exists, the existing entry is returned.",
  inputSchema: z.object({
    scope: z
      .enum(["general", "user"])
      .describe(
        "Use general only for information that applies to every customer. Use user for a fact about one customer.",
      ),
    content: z
      .string()
      .min(1)
      .describe(
        "The reusable answer or fact, written as a standalone statement. Do not include greetings or customer-specific chatter in general knowledge.",
      ),
    title: z
      .string()
      .optional()
      .describe("A short label that makes the entry easy to find."),
    interactionId: z
      .string()
      .uuid()
      .optional()
      .describe(
        "Maintainer channel only: the escalation whose customer owns this user-specific knowledge. Required when a maintainer saves user-specific knowledge.",
      ),
  }),
  async execute({ scope: knowledgeScope, content, title, interactionId }, ctx) {
    const authScope = readScope(ctx.session.auth.current);
    const db = getDatabase();

    const result = await saveKnowledgeForScope(db, authScope, {
      knowledgeScope,
      content,
      title: title ?? null,
      interactionId: interactionId ?? null,
      metadata: {
        channel: authScope.platform,
        conversationId: authScope.conversationId,
      },
    });

    return {
      ok: true,
      created: result.created,
      entry: {
        id: result.entry.id,
        scope: result.entry.scope,
        title: result.entry.title,
        content: result.entry.content,
        source: result.entry.source,
        updatedAt: toIsoString(result.entry.updatedAt),
      },
    };
  },
});
