import { createDiscordAdapter } from "@chat-adapter/discord";
import { createPostgresState } from "@chat-adapter/state-pg";
import { createWhatsAppAdapter } from "@chat-adapter/whatsapp";
import type { Adapter, Message, Thread } from "chat";
import { chatSdkChannel, messageContentOf } from "eve/channels/chat-sdk";
import {
  buildSessionAuth,
  tryReadScope,
  type FrontdeskRole,
} from "../../src/auth/scope.js";
import { registerChatRuntime } from "../../src/chat/registry.js";
import { getDatabase, ensureRuntimeBootstrap, getRuntimeConfig } from "../../src/runtime.js";
import { findConnectionByExternalId } from "../../src/db/repositories/connections.js";
import {
  ensureConversation,
  findConversationById,
} from "../../src/db/repositories/conversations.js";
import {
  findInteractionByMaintainerMessageId,
  findInteractionByMaintainerThreadId,
  listOpenInteractions,
} from "../../src/db/repositories/interactions.js";
import {
  recordMessage,
  updateMessageDeliveryStatus,
} from "../../src/db/repositories/messages.js";
import type {
  Interaction,
  Platform,
} from "../../src/db/schema.js";

const config = getRuntimeConfig();

const adapters: Record<string, Adapter> = {};
const platformByAdapter: Partial<Record<string, Platform>> = {};
const adapterByPlatform: Partial<Record<Platform, string>> = {};

/**
 * Both adapters are always registered. EVE derives the webhook route plan at
 * build time, so the adapter names must not depend on whether credentials are
 * present in the build environment. Unconfigured platforms get placeholders:
 * their webhooks fail verification and `handleInbound` ignores them.
 */
adapters.discord = createDiscordAdapter({
  botToken: config.discord?.botToken ?? "unconfigured",
  publicKey: config.discord?.publicKey ?? "0".repeat(64),
  applicationId: config.discord?.applicationId ?? "unconfigured",
  respondToChannelIds: config.discord?.respondToChannelIds ?? [],
  userName: config.botName,
}) as Adapter;
platformByAdapter.discord = "discord";
adapterByPlatform.discord = "discord";

adapters.whatsapp = createWhatsAppAdapter({
  accessToken: config.whatsapp?.accessToken ?? "unconfigured",
  appSecret: config.whatsapp?.appSecret ?? "unconfigured",
  phoneNumberId: config.whatsapp?.phoneNumberId ?? "unconfigured",
  verifyToken: config.whatsapp?.verifyToken ?? "unconfigured",
  userName: config.botName,
}) as Adapter;
platformByAdapter.whatsapp = "whatsapp";
adapterByPlatform.whatsapp = "whatsapp";

export const { bot, channel, send } = chatSdkChannel({
  userName: config.botName,
  adapters,
  state: createPostgresState({
    url: config.databaseUrl,
    keyPrefix: "frontdesk",
    autoCreateSchema: true,
  }),
  // Discord and WhatsApp both deliver one final message reliably. Avoiding
  // streamed edits keeps the canonical message record and the visible reply in
  // lockstep.
  streaming: false,
  concurrency: "concurrent",
  events: {
    async "content.completed"(event, ctx) {
      await persistAndPostReply(event.data, ctx);
    },
  },
});

registerChatRuntime({ bot, platformByAdapter, adapterByPlatform });

function platformForThread(thread: Thread): Platform | null {
  const prefix = thread.id.split(":")[0];
  return prefix === "discord" || prefix === "whatsapp" ? prefix : null;
}

function rawChannelId(thread: Thread): string {
  const parts = thread.channelId.split(":");
  return parts[parts.length - 1] ?? thread.channelId;
}

function isMaintainerThread(platform: Platform, thread: Thread): boolean {
  if (platform !== "discord") return false;
  const key = config.discord?.maintainerChannelKey;
  return key !== null && key !== undefined && rawChannelId(thread) === key;
}

function externalIdForPlatform(platform: Platform): string | null {
  if (platform === "discord") return config.discord?.applicationId ?? null;
  return config.whatsapp?.phoneNumberId ?? null;
}

async function handleInbound(thread: Thread, message: Message): Promise<void> {
  if (message.author.isMe || message.author.isBot === true) return;

  const platform = platformForThread(thread);
  if (!platform) return;

  const externalId = externalIdForPlatform(platform);
  if (!externalId) return;

  const bootstrap = await ensureRuntimeBootstrap();
  const db = getDatabase();
  const scope = { tenantId: bootstrap.tenant.id, botId: bootstrap.bot.id };

  const connection = await findConnectionByExternalId(
    db,
    scope,
    platform,
    externalId,
  );
  if (!connection) {
    console.error(
      `No ${platform} connection is registered for external id ${externalId}`,
    );
    return;
  }

  const role: FrontdeskRole = isMaintainerThread(platform, thread)
    ? "maintainer"
    : "customer";
  const kind =
    role === "maintainer" ? "maintainer" : thread.isDM ? "dm" : "group";
  const displayName = message.author.fullName || message.author.userName;
  const content =
    message.text.trim() ||
    (message.attachments.length > 0 ? "[attachment]" : "");
  if (!content) return;

  const conversation = await ensureConversation(db, {
    ...scope,
    connectionId: connection.id,
    platform,
    externalThreadId: thread.id,
    externalChannelId: thread.channelId,
    kind,
    title:
      role === "maintainer"
        ? "Provider maintainer channel"
        : `${displayName} on ${platform}`,
    ...(role === "customer"
      ? {
          participantExternalId: message.author.userId,
          participantName: displayName,
        }
      : {}),
  });

  const inbound = await recordMessage(db, {
    ...scope,
    conversationId: conversation.id,
    externalMessageId: message.id,
    direction: "inbound",
    authorExternalId: message.author.userId,
    authorName: displayName,
    content,
    contentJson: {
      platform,
      attachmentCount: message.attachments.length,
      isMention: message.isMention ?? false,
    },
    dedupeKey: message.id,
    deliveryStatus: "pending",
  });

  if (!inbound.inserted && inbound.message.deliveryStatus === "sent") {
    return;
  }

  await thread.subscribe();

  const auth = buildSessionAuth({
    tenantId: scope.tenantId,
    botId: scope.botId,
    connectionId: connection.id,
    conversationId: conversation.id,
    platform,
    externalUserId: message.author.userId,
    externalThreadId: thread.id,
    role,
    displayName,
  });

  const context =
    role === "maintainer"
      ? await maintainerContext(db, scope, conversation.id, thread, message)
      : [`Customer: ${displayName} on ${platform}.`];

  const modelMessage =
    role === "maintainer"
      ? `Maintainer ${displayName}: ${content}`
      : messageContentOf(message);

  try {
    await send(modelMessage, {
      thread,
      auth,
      idempotencyKey: message.id,
      title:
        role === "maintainer"
          ? "Maintainer reply"
          : content.slice(0, 80),
      context,
    });
    await updateMessageDeliveryStatus(
      db,
      scope,
      inbound.message.id,
      "sent",
      message.id,
    );
  } catch (error) {
    console.error(
      `Failed to dispatch ${platform} message ${message.id} to eve`,
      error,
    );
    throw error;
  }
}

async function maintainerContext(
  db: ReturnType<typeof getDatabase>,
  scope: { tenantId: string; botId: string },
  maintainerConversationId: string,
  thread: Thread,
  message: Message,
): Promise<string[]> {
  const context = [
    "This message is in the provider maintainer channel, not a customer conversation.",
  ];

  let interaction: Interaction | null = null;
  if (message.replyTo?.id) {
    interaction = await findInteractionByMaintainerMessageId(
      db,
      scope,
      message.replyTo.id,
    );
  }
  if (!interaction) {
    interaction = await findInteractionByMaintainerThreadId(
      db,
      scope,
      thread.id,
    );
  }

  if (!interaction && config.discord?.maintainerChannelId) {
    const open = await listOpenInteractions(db, {
      ...scope,
      maintainerChannelId: config.discord.maintainerChannelId,
      limit: 10,
    });
    if (open.length === 1) {
      interaction = open[0]!;
    } else if (open.length > 1) {
      context.push(
        `There are ${open.length} open escalations in this channel. Use list_open_interactions to choose one before calling answer_interaction.`,
      );
    }
  }

  if (!interaction) {
    context.push(
      "No specific escalation was referenced. Use list_open_interactions if the maintainer is answering a customer question.",
    );
    return context;
  }

  const customerConversation = await findConversationById(
    db,
    scope,
    interaction.conversationId,
  );
  const customerName =
    customerConversation?.participantName ?? "the customer";
  const customerPlatform = customerConversation?.platform ?? "unknown";

  context.push(
    `This message relates to escalation ${interaction.id} from ${customerName} on ${customerPlatform}.`,
    `Customer question: ${interaction.question}`,
    `Use answer_interaction with interactionId "${interaction.id}" to relay the maintainer's answer. Classify reusable information as general or user-specific knowledge when you save it.`,
  );

  if (interaction.maintainerMessageId) {
    context.push(
      `The escalation notice in this channel has message id ${interaction.maintainerMessageId}.`,
    );
  }
  if (maintainerConversationId) {
    context.push(`Maintainer conversation id: ${maintainerConversationId}.`);
  }

  return context;
}

async function persistAndPostReply(
  data: {
    readonly partId: string;
    readonly kind: string;
    readonly phase: string;
    readonly value?: unknown;
  },
  ctx: {
    readonly session: { readonly id: string; readonly auth: { readonly current: unknown } };
    readonly channel: { readonly thread: Thread | null };
  },
): Promise<void> {
  if (data.kind !== "text" || data.phase !== "reply") return;
  const text = typeof data.value === "string" ? data.value.trim() : "";
  if (!text) return;

  const thread = ctx.channel.thread;
  if (!thread) return;

  const scope = tryReadScope(
    ctx.session.auth.current as Parameters<typeof tryReadScope>[0],
  );
  const db = getDatabase();
  let recordedMessageId: string | null = null;

  if (scope) {
    const dedupeKey = `outbound:${ctx.session.id}:${data.partId}`;
    const recorded = await recordMessage(db, {
      tenantId: scope.tenantId,
      botId: scope.botId,
      conversationId: scope.conversationId,
      direction: "outbound",
      authorName: config.botName,
      content: text,
      dedupeKey,
      deliveryStatus: "pending",
      metadata: {
        partId: data.partId,
        phase: data.phase,
        platform: scope.platform,
      },
    });
    if (!recorded.inserted) return;
    recordedMessageId = recorded.message.id;
  }

  try {
    const sent = await thread.post({ markdown: text });
    if (scope && recordedMessageId) {
      await updateMessageDeliveryStatus(
        db,
        scope,
        recordedMessageId,
        "sent",
        sent.id,
      );
    }
  } catch (error) {
    if (scope && recordedMessageId) {
      await updateMessageDeliveryStatus(
        db,
        scope,
        recordedMessageId,
        "failed",
      );
    }
    console.error("Failed to post the agent reply", error);
    throw error;
  }
}

bot.onNewMention(handleInbound);
bot.onSubscribedMessage(handleInbound);

export default channel;
