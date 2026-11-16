import { defineTool } from "eve/tools";
import { z } from "zod";
import { readScope } from "../../src/auth/scope.js";
import { postToChannel } from "../../src/chat/delivery.js";
import { recordAuditEvent } from "../../src/db/repositories/audit.js";
import { findConnectionById } from "../../src/db/repositories/connections.js";
import {
  createInteraction,
  setInteractionNotification,
} from "../../src/db/repositories/interactions.js";
import { findLatestInboundMessage } from "../../src/db/repositories/messages.js";
import { getDatabase } from "../../src/runtime.js";
import {
  escalationDedupeKey,
  resolveMaintainerDestination,
} from "../../src/agent/tool-helpers.js";

export default defineTool({
  description:
    "Forward an unanswered customer question to the provider's private maintainer channel. Use this when the knowledge base has no answer, the question needs an account-specific decision or action, the customer asks for a human, or the customer is still unsatisfied after an answer. Do not use it for questions the knowledge base can answer. This tool posts the question once; if the same inbound message was already escalated, it returns the existing escalation instead of posting again.",
  inputSchema: z.object({
    question: z
      .string()
      .min(1)
      .describe(
        "The customer's unanswered question, restated clearly and completely. Do not add facts the customer did not provide.",
      ),
    context: z
      .string()
      .optional()
      .describe(
        "Relevant context the maintainer needs: what the customer already tried, which answer was already given, or why the question is account-specific.",
      ),
    priority: z.enum(["low", "normal", "high", "urgent"]).optional(),
  }),
  async execute({ question, context, priority }, ctx) {
    const scope = readScope(ctx.session.auth.current);
    if (scope.role !== "customer") {
      throw new Error(
        "Only a customer conversation can escalate a question. In the maintainer channel, use list_open_interactions and answer_interaction.",
      );
    }

    const db = getDatabase();
    const connection = await findConnectionById(db, scope, scope.connectionId);
    if (!connection) {
      throw new Error(
        "The customer's platform connection is missing. Ask the provider to check the deployment configuration.",
      );
    }

    const destination = await resolveMaintainerDestination(db, scope, connection);
    if (!destination) {
      return {
        ok: false,
        reason: "no_maintainer_channel",
        message:
          "This platform has no provider maintainer channel configured, so I cannot forward the question. Tell the customer that a maintainer will need to follow up through another support channel, and do not promise a response time.",
      };
    }
    const maintainerChannelId = destination.channelId;

    const latestInbound = await findLatestInboundMessage(db, {
      tenantId: scope.tenantId,
      botId: scope.botId,
      conversationId: scope.conversationId,
    });

    const dedupeKey = escalationDedupeKey({
      conversationId: scope.conversationId,
      sourceMessageId: latestInbound?.id ?? null,
      question,
    });

    const created = await createInteraction(db, {
      tenantId: scope.tenantId,
      botId: scope.botId,
      conversationId: scope.conversationId,
      sourceMessageId: latestInbound?.id ?? null,
      question: question.trim(),
      context: context?.trim() || null,
      priority,
      dedupeKey,
      maintainerConnectionId: destination.connectionId,
      maintainerChannelId,
      metadata: {
        platform: scope.platform,
        customerName: scope.displayName,
        customerExternalId: scope.externalUserId,
      },
    });

    let interaction = created.interaction;

    if (interaction.status === "cancelled" || interaction.status === "resolved") {
      return {
        ok: false,
        reason: "already_closed",
        message:
          "This question already has a closed escalation. Do not reopen it automatically. If the customer needs more help, ask a new, specific question or escalate only if they remain unsatisfied.",
      };
    }

    if (interaction.maintainerMessageId) {
      return {
        ok: true,
        interactionId: interaction.id,
        status: interaction.status,
        alreadyEscalated: true,
        message:
          "This question is already with the provider maintainers. Tell the customer it has been forwarded and do not post it again.",
      };
    }

    const customerName = scope.displayName ?? "A customer";
    const markdown = [
      "**New customer question**",
      "",
      `**Customer:** ${customerName} (${scope.platform})`,
      `**Question:** ${question.trim()}`,
      ...(context?.trim() ? [`**Context:** ${context.trim()}`] : []),
      `**Escalation ID:** \`${interaction.id}\``,
      "",
      "Reply in this channel. I will relay your answer to the customer and can save it to the knowledge base.",
    ].join("\n");

    try {
      const posted = await postToChannel(maintainerChannelId, markdown);
      const updated = await setInteractionNotification(db, scope, interaction.id, {
        maintainerConnectionId: connection.id,
        maintainerChannelId,
        maintainerThreadId: posted.threadId,
        maintainerMessageId: posted.messageId,
        status: "waiting_for_maintainer",
      });
      if (updated) interaction = updated;
    } catch (error) {
      console.error("Failed to notify provider maintainers", error);
      return {
        ok: false,
        reason: "notification_failed",
        message:
          "I could not reach the provider maintainer channel. Tell the customer the question could not be forwarded right now and that they should try again shortly. Do not claim it was delivered.",
      };
    }

    await recordAuditEvent(db, {
      tenantId: scope.tenantId,
      botId: scope.botId,
      actorType: "customer",
      actorExternalId: scope.externalUserId,
      action: "interaction.escalated",
      subjectType: "interaction",
      subjectId: interaction.id,
      data: {
        platform: scope.platform,
        conversationId: scope.conversationId,
        priority: interaction.priority,
      },
    });

    return {
      ok: true,
      interactionId: interaction.id,
      status: interaction.status,
      alreadyEscalated: false,
      message:
        "The question was forwarded to the provider maintainers. Tell the customer it has been escalated and that a maintainer will follow up. Do not promise a specific response time.",
    };
  },
});
