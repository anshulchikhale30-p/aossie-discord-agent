import type { DiscordAdapter } from "@chat-adapter/discord";
import { setTimeout as delay } from "node:timers/promises";
import { bot } from "../agent/channels/chat.js";
import { getRuntimeConfig } from "../src/runtime.js";

const config = getRuntimeConfig();
if (!config.discord) {
  console.error(
    "Discord is not configured. Set DISCORD_BOT_TOKEN, DISCORD_PUBLIC_KEY, and DISCORD_APPLICATION_ID.",
  );
  process.exit(1);
}

const discord = config.discord;
const adapter = bot.getAdapter("discord") as unknown as DiscordAdapter;

const controller = new AbortController();
const stop = (signal: string) => {
  console.log(`Received ${signal}; stopping the Discord Gateway listener.`);
  controller.abort();
};
process.on("SIGINT", () => stop("SIGINT"));
process.on("SIGTERM", () => stop("SIGTERM"));

await bot.initialize();

async function runListener(): Promise<void> {
  let resolveDone!: () => void;
  let rejectDone!: (error: unknown) => void;
  const done = new Promise<void>((resolve, reject) => {
    resolveDone = resolve;
    rejectDone = reject;
  });

  const response = await adapter.startGatewayListener(
    {
      waitUntil(promise) {
        promise.then(resolveDone, rejectDone);
      },
    },
    discord.gatewayDurationMs,
    controller.signal,
    discord.gatewayWebhookUrl,
  );

  const body = await response.text();
  if (!response.ok) {
    throw new Error(
      `Failed to start the Discord Gateway listener: ${response.status} ${body}`,
    );
  }

  console.log(body);
  await done;
}

while (!controller.signal.aborted) {
  try {
    await runListener();
  } catch (error) {
    if (controller.signal.aborted) break;
    console.error("Discord Gateway listener failed", error);
  }

  if (controller.signal.aborted) break;
  console.log("Discord Gateway listener stopped; restarting in 2 seconds.");
  await delay(2_000);
}

console.log("Discord Gateway listener stopped.");
