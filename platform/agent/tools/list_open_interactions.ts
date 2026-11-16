import { defineTool } from "eve/tools";
import { z } from "zod";
import { readScope } from "../../src/auth/scope.js";
import { findConnectionById } from "../../src/db/repositories/connections.js";
import { findConversationById } from "../../src/db/repositories/conversations.js";
import { listOpenInteractions } from "../../src/db/repositories/interactions.js";
import { getDatabase } from "../../src/runtime.js";
import { toIsoString } from "../../src/agent/tool-helpers.js";

export default defineTool({
  description:
    "List the customer questions that are still waiting for a provider maintainer in this maintainer channel. Use it when a maintainer message does not name an escalation, or when several questions are open and you need the right interactionId before calling answer_interaction.",
  inputSchema: z.object({
    limit: z.number().int().min(1).max(50).optional(),
  }),
  async execute({ limit }, ctx) {
    const scope = readScope(ctx.session.auth.current);
    if (scope.role !== "maintainer") {
      throw new Error(
        "Only the provider maintainer channel can list open escalations.",
      );
    }

    const db = getDatabase();
    const connection = await findConnectionById(db, scope, scope.connectionId);
    const maintainerChannelId = connection?.maintainerChannelId ?? null;
    if (!maintainerChannelId) {
      return {
        interactions: [],
        message:
          "This maintainer channel is not registered on the platform connection. Ask the provider to check DISCORD_MAINTAINER_CHANNEL_ID.",
      };
    }

    const open = await listOpenInteractions(db, {
      tenantId: scope.tenantId,
      botId: scope.botId,
      maintainerChannelId,
      limit,
    });

    const interactions = await Promise.all(
      open.map(async (interaction) => {
        const conversation = await findConversationById(
          db,
          scope,
          interaction.conversationId,
        );
        return {
          id: interaction.id,
          question: interaction.question,
          context: interaction.context,
          status: interaction.status,
          priority: interaction.priority,
          responseText: interaction.responseText,
          createdAt: toIsoString(interaction.createdAt),
          updatedAt: toIsoString(interaction.updatedAt),
          customer: {
            name: conversation?.participantName ?? null,
            platform: conversation?.platform ?? null,
          },
        };
      }),
    );

    return {
      interactions,
      message:
        interactions.length === 0
          ? "There are no open escalations in this channel."
          : `There ${interactions.length === 1 ? "is" : "are"} ${interactions.length} open escalation${interactions.length === 1 ? "" : "s"}. Use the id of the one the maintainer is answering.`,
    };
  },
});
