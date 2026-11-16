import { getChatRuntime } from "./registry.js";

export interface PostedMessage {
  messageId: string;
  threadId: string;
}

/** Post a top-level message to a Chat SDK channel. */
export async function postToChannel(
  channelId: string,
  markdown: string,
): Promise<PostedMessage> {
  const { bot } = getChatRuntime();
  const sent = await bot.channel(channelId).post({ markdown });
  return { messageId: sent.id, threadId: sent.threadId };
}

/** Post a message to an existing Chat SDK thread. */
export async function postToThread(
  threadId: string,
  markdown: string,
): Promise<PostedMessage> {
  const { bot } = getChatRuntime();
  const sent = await bot.thread(threadId).post({ markdown });
  return { messageId: sent.id, threadId: sent.threadId };
}

/**
 * Send a message to the customer conversation that produced an interaction.
 * The interaction stores the full Chat SDK thread id, so this works from a
 * maintainer session without the customer's EVE session being active.
 */
export async function relayToCustomer(
  externalThreadId: string,
  markdown: string,
): Promise<PostedMessage> {
  return postToThread(externalThreadId, markdown);
}
