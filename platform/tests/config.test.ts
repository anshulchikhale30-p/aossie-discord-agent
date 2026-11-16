import { describe, expect, it } from "vitest";
import {
  loadConfig,
  toDiscordChannelId,
  toDiscordMaintainerChannel,
} from "../src/config.js";

const discordEnv = {
  DISCORD_BOT_TOKEN: "bot-token",
  DISCORD_PUBLIC_KEY: "public-key",
  DISCORD_APPLICATION_ID: "application-id",
} as const;

describe("environment configuration", () => {
  it("accepts a raw maintainer channel id and builds a postable id", () => {
    expect(toDiscordMaintainerChannel("1234567890")).toEqual({
      channelId: "discord:unknown:1234567890",
      channelKey: "1234567890",
    });
    expect(toDiscordMaintainerChannel("discord:guild-1:1234567890")).toEqual({
      channelId: "discord:guild-1:1234567890",
      channelKey: "1234567890",
    });
    expect(toDiscordMaintainerChannel(null)).toEqual({
      channelId: null,
      channelKey: null,
    });
    expect(toDiscordChannelId("discord:guild-1:1234567890")).toBe(
      "1234567890",
    );
  });

  it("loads Discord settings and always answers in the maintainer channel", () => {
    const config = loadConfig({
      ...discordEnv,
      DISCORD_MAINTAINER_CHANNEL_ID: "999",
      DISCORD_RESPOND_TO_CHANNEL_IDS: "111, discord:guild-1:222",
      LLM_MODEL: "ignored-here",
    });

    expect(config.discord).not.toBeNull();
    expect(config.discord?.maintainerChannelId).toBe("discord:unknown:999");
    expect(config.discord?.maintainerChannelKey).toBe("999");
    expect(config.discord?.respondToChannelIds).toEqual(["111", "222", "999"]);
    expect(config.whatsapp).toBeNull();
    expect(config.databaseUrl).toBe(
      "postgres://frontdesk:frontdesk@localhost:5432/frontdesk",
    );
  });

  it("does not enable a platform with incomplete credentials", () => {
    const config = loadConfig({
      DISCORD_BOT_TOKEN: "bot-token",
      WHATSAPP_ACCESS_TOKEN: "access-token",
      WHATSAPP_APP_SECRET: "app-secret",
    });

    expect(config.discord).toBeNull();
    expect(config.whatsapp).toBeNull();
  });

  it("loads WhatsApp when all credentials are present", () => {
    const config = loadConfig({
      WHATSAPP_ACCESS_TOKEN: "access-token",
      WHATSAPP_APP_SECRET: "app-secret",
      WHATSAPP_PHONE_NUMBER_ID: "phone-id",
      WHATSAPP_VERIFY_TOKEN: "verify-token",
    });

    expect(config.whatsapp).toEqual({
      accessToken: "access-token",
      appSecret: "app-secret",
      phoneNumberId: "phone-id",
      verifyToken: "verify-token",
    });
  });

  it("rejects invalid numeric settings", () => {
    expect(() =>
      loadConfig({
        ...discordEnv,
        DISCORD_GATEWAY_DURATION_MS: "0",
      }),
    ).toThrow(/Invalid environment configuration/);
  });
});
