import type { Chat } from "chat";
import type { Platform } from "../db/schema.js";

export interface ChatRuntime {
  bot: Chat;
  platformByAdapter: Partial<Record<string, Platform>>;
  adapterByPlatform: Partial<Record<Platform, string>>;
}

let runtime: ChatRuntime | null = null;

/**
 * The channel module owns the Chat SDK instance. Tools and delivery helpers use
 * this registry so they never import the channel module (which would create a
 * cycle through eve's channel discovery).
 */
export function registerChatRuntime(next: ChatRuntime): void {
  runtime = next;
}

export function getChatRuntime(): ChatRuntime {
  if (!runtime) {
    throw new Error(
      "Chat runtime is not registered. Load agent/channels/chat.ts before using delivery helpers.",
    );
  }
  return runtime;
}

export function getPlatformForAdapter(
  adapterName: string,
): Platform | null {
  return getChatRuntime().platformByAdapter[adapterName] ?? null;
}

export function getAdapterNameForPlatform(
  platform: Platform,
): string | null {
  return getChatRuntime().adapterByPlatform[platform] ?? null;
}
