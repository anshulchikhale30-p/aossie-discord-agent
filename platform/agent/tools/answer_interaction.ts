import { defineTool } from "eve/tools";
import { z } from "zod";
import { readScope } from "../../src/auth/scope.js";
import { relayToCustomer } from "../../src/chat/delivery.js";
import { recordAuditEvent } from "../../src/db/repositories/audit.js";
import {
  recordInteractionAnswer,
  resolveInteraction,
} from "../../src/db/repositories/interactions.js";
import {
  recordMessage,
  updateMessageDeliveryStatus,
} from "../../src/db/repositories/messages.js";
import { getDatabase, getRuntimeConfig } from "../../src/runtime.js";
import {
  loadInteractionCustomer,
  saveKnowledgeForScope,
} from "../../src/agent/tool-helpers.js";

export default defineTool({
  description:
    "Relay a maintainer's answer to the customer who asked an escalated question, then close the escalation. Use it after a maintainer replies in this channel. The answer is sent to the customer's original conversation, not posted in the maintainer channel. Optionally save the answer as general knowledge (reusable for every customer) or user-specific knowledge (only for this customer). If the answer was already delivered, the tool does not send it twice.",
  inputSchema: z.object({
    interactionId: z
      .string()
      .uuid()
      .describe(
        "The escalation being answered. Use list_open_interactions if the maintainer did not name it.",
      ),
    answer: z
      .string()
      .min(1)
      .describe(
        "The customer-facing answer, written in the bot's voice. Do not include maintainer-only notes, internal IDs, or instructions for the customer to contact the maintainer channel directly.",
      ),
    saveAsKnowledge: z
      .enum(["general", "user", "none"])
      .optional()
      .describe(
        "Classify the answer before saving it. general: true for every customer. user: only about this customer. none: do not save a one-off answer.",
      ),
    knowledgeTitle: z
      .string()
      .optional()
      .describe("A short label for the saved knowledge entry."),
  }),
  async execute(
    { interactionId, answer, saveAsKnowledge, knowledgeTitle },
    ctx,
  ) {
    const scope = readScope(ctx.session.auth.current);
    if (scope.role !== "maintainer") {
      throw new Error(
        "Only the provider maintainer channel can answer an escalation.",
      );
    }

    const trimmedAnswer = answer.trim();
    if (!trimmedAnswer) {
      throw new Error("The customer-facing answer cannot be empty.");
    }

    const db = getDatabase();
    const { interaction, conversation } = await loadInteractionCustomer(
      db,
      scope,
      interactionId,
    );

    if (interaction.status === "resolved") {
      return {
        ok: false,
        reason: "already_resolved",
        message:
          "This escalation is already resolved. Do not send the answer again. If the customer needs more help, ask a new question or escalate only if they remain unsatisfied.",
      };
    }
    if (interaction.status === "cancelled") {
      return {
        ok: false,
        reason: "cancelled",
        message:
          "This escalation was cancelled. Do not send the answer. Ask the maintainer whether a new escalation should be created.",
      };
    }

    await recordInteractionAnswer(db, scope, interaction.id, {
      responseText: trimmedAnswer,
      respondedByExternalId: scope.externalUserId,
      status: "response_received",
    });

    let knowledge:
      | {
          saved: true;
          scope: "general" | "user";
          entryId: string;
          created: boolean;
        }
      | { saved: false }
      | null = null;

    if (saveAsKnowledge && saveAsKnowledge !== "none") {
      const saved = await saveKnowledgeForScope(db, scope, {
        knowledgeScope: saveAsKnowledge,
        content: trimmedAnswer,
        title:
          knowledgeTitle?.trim() ||
          interaction.question.slice(0, 120) ||
          null,
        interactionId: interaction.id,
        metadata: { interactionId: interaction.id },
      });
      knowledge = {
        saved: true,
        scope: saved.entry.scope,
        entryId: saved.entry.id,
        created: saved.created,
      };
    } else if (saveAsKnowledge === "none") {
      knowledge = { saved: false };
    }

    const dedupeKey = `relay:interaction:${interaction.id}`;
    const recorded = await recordMessage(db, {
      tenantId: scope.tenantId,
      botId: scope.botId,
      conversationId: conversation.id,
      direction: "outbound",
      authorName: getRuntimeConfig().botName,
      content: trimmedAnswer,
      dedupeKey,
      deliveryStatus: "pending",
      metadata: {
        interactionId: interaction.id,
        relayedByExternalId: scope.externalUserId,
        platform: conversation.platform,
      },
    });

    if (!recorded.inserted && recorded.message.deliveryStatus === "sent") {
      await resolveInteraction(db, scope, interaction.id);
      return {
        ok: true,
        interactionId: interaction.id,
        delivered: true,
        alreadyDelivered: true,
        knowledge,
        message:
          "This answer was already delivered to the customer. The escalation is resolved.",
      };
    }

    try {
      const posted = await relayToCustomer(
        conversation.externalThreadId,
        trimmedAnswer,
      );
      await updateMessageDeliveryStatus(
        db,
        scope,
        recorded.message.id,
        "sent",
        posted.messageId,
      );
      await resolveInteraction(db, scope, interaction.id);
      await recordAuditEvent(db, {
        tenantId: scope.tenantId,
        botId: scope.botId,
        actorType: "maintainer",
        actorExternalId: scope.externalUserId,
        action: "interaction.answered",
        subjectType: "interaction",
        subjectId: interaction.id,
        data: {
          platform: conversation.platform,
          conversationId: conversation.id,
          knowledgeScope: knowledge?.saved ? knowledge.scope : null,
        },
      });

      return {
        ok: true,
        interactionId: interaction.id,
        delivered: true,
        alreadyDelivered: false,
        customerMessageId: posted.messageId,
        knowledge,
        message:
          "The answer was delivered to the customer and the escalation is resolved. Briefly confirm this to the maintainer.",
      };
    } catch (error) {
      await updateMessageDeliveryStatus(
        db,
        scope,
        recorded.message.id,
        "failed",
      );
      console.error("Failed to relay maintainer answer to customer", error);
      return {
        ok: false,
        reason: "delivery_failed",
        message:
          "The answer could not be delivered to the customer. The escalation is still open. Tell the maintainer delivery failed and that they can retry.",
      };
    }
  },
});
