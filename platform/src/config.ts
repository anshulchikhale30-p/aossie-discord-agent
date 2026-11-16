import { z } from "zod";

const optionalString = z.string().trim().min(1).optional();

const envSchema = z.object({
  NODE_ENV: z.string().default("development"),
  DATABASE_URL: z
    .string()
    .trim()
    .min(1)
    .default("postgres://frontdesk:frontdesk@localhost:5432/frontdesk"),

  TENANT_SLUG: z.string().trim().min(1).default("aossie"),
  TENANT_NAME: z.string().trim().min(1).default("AOSSIE"),
  BOT_SLUG: z.string().trim().min(1).default("frontdesk"),
  BOT_NAME: z.string().trim().min(1).default("AOSSIE Front Desk"),
  BOT_SYSTEM_PROMPT: optionalString,

  DISCORD_BOT_TOKEN: optionalString,
  DISCORD_PUBLIC_KEY: optionalString,
  DISCORD_APPLICATION_ID: optionalString,
  DISCORD_MAINTAINER_CHANNEL_ID: optionalString,
  DISCORD_RESPOND_TO_CHANNEL_IDS: optionalString,
  DISCORD_GATEWAY_WEBHOOK_URL: z
    .string()
    .trim()
    .min(1)
    .default("http://127.0.0.1:3000/eve/v1/discord"),
  DISCORD_GATEWAY_DURATION_MS: z.coerce
    .number()
    .int()
    .positive()
    .default(6 * 60 * 60 * 1000),

  WHATSAPP_ACCESS_TOKEN: optionalString,
  WHATSAPP_APP_SECRET: optionalString,
  WHATSAPP_PHONE_NUMBER_ID: optionalString,
  WHATSAPP_VERIFY_TOKEN: optionalString,

  PUBLIC_BASE_URL: optionalString,
});

export interface AppConfig {
  nodeEnv: string;
  databaseUrl: string;
  tenantSlug: string;
  tenantName: string;
  botSlug: string;
  botName: string;
  botSystemPrompt: string | null;
  discord: {
    botToken: string;
    publicKey: string;
    applicationId: string;
    /** Full Chat SDK channel id used for proactive posts. */
    maintainerChannelId: string | null;
    /** Raw Discord channel id used to recognize maintainer-channel events. */
    maintainerChannelKey: string | null;
    respondToChannelIds: string[];
    gatewayWebhookUrl: string;
    gatewayDurationMs: number;
  } | null;
  whatsapp: {
    accessToken: string;
    appSecret: string;
    phoneNumberId: string;
    verifyToken: string;
  } | null;
  publicBaseUrl: string | null;
}

let cached: AppConfig | null = null;

/**
 * The Discord adapter compares raw channel ids, not full Chat SDK ids. Accept
 * both `discord:<guild>:<channel>` and a bare channel id.
 */
export function toDiscordChannelId(value: string): string {
  const trimmed = value.trim();
  if (!trimmed.startsWith("discord:")) return trimmed;
  const parts = trimmed.split(":");
  return parts[parts.length - 1] ?? trimmed;
}

/**
 * Discord needs a full `discord:<guild>:<channel>` id for channel posts, but
 * operators normally configure only the channel id. When the guild is absent
 * the adapter still posts correctly because it only reads the channel segment;
 * inbound events are matched by the raw channel key.
 */
export function toDiscordMaintainerChannel(
  value: string | null | undefined,
): { channelId: string | null; channelKey: string | null } {
  if (!value) return { channelId: null, channelKey: null };
  const trimmed = value.trim();
  const channelKey = toDiscordChannelId(trimmed);
  const parts = trimmed.split(":");
  const channelId =
    trimmed.startsWith("discord:") && parts.length >= 3
      ? trimmed
      : `discord:unknown:${channelKey}`;
  return { channelId, channelKey };
}

function splitIds(value: string | undefined): string[] {
  if (!value) return [];
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map(toDiscordChannelId);
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const parsed = envSchema.safeParse(env);
  if (!parsed.success) {
    const details = parsed.error.issues
      .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
      .join("; ");
    throw new Error(`Invalid environment configuration: ${details}`);
  }
  const value = parsed.data;

  const discordConfigured =
    value.DISCORD_BOT_TOKEN &&
    value.DISCORD_PUBLIC_KEY &&
    value.DISCORD_APPLICATION_ID;

  const whatsappConfigured =
    value.WHATSAPP_ACCESS_TOKEN &&
    value.WHATSAPP_APP_SECRET &&
    value.WHATSAPP_PHONE_NUMBER_ID &&
    value.WHATSAPP_VERIFY_TOKEN;

  const { channelId: maintainerChannelId, channelKey: maintainerChannelKey } =
    toDiscordMaintainerChannel(value.DISCORD_MAINTAINER_CHANNEL_ID);

  const respondToChannelIds = splitIds(value.DISCORD_RESPOND_TO_CHANNEL_IDS);
  if (maintainerChannelKey && !respondToChannelIds.includes(maintainerChannelKey)) {
    respondToChannelIds.push(maintainerChannelKey);
  }

  return {
    nodeEnv: value.NODE_ENV,
    databaseUrl: value.DATABASE_URL,
    tenantSlug: value.TENANT_SLUG,
    tenantName: value.TENANT_NAME,
    botSlug: value.BOT_SLUG,
    botName: value.BOT_NAME,
    botSystemPrompt: value.BOT_SYSTEM_PROMPT ?? null,
    discord: discordConfigured
      ? {
          botToken: value.DISCORD_BOT_TOKEN!,
          publicKey: value.DISCORD_PUBLIC_KEY!,
          applicationId: value.DISCORD_APPLICATION_ID!,
          maintainerChannelId,
          maintainerChannelKey,
          respondToChannelIds,
          gatewayWebhookUrl: value.DISCORD_GATEWAY_WEBHOOK_URL,
          gatewayDurationMs: value.DISCORD_GATEWAY_DURATION_MS,
        }
      : null,
    whatsapp: whatsappConfigured
      ? {
          accessToken: value.WHATSAPP_ACCESS_TOKEN!,
          appSecret: value.WHATSAPP_APP_SECRET!,
          phoneNumberId: value.WHATSAPP_PHONE_NUMBER_ID!,
          verifyToken: value.WHATSAPP_VERIFY_TOKEN!,
        }
      : null,
    publicBaseUrl: value.PUBLIC_BASE_URL ?? null,
  };
}

export function getConfig(): AppConfig {
  cached ??= loadConfig();
  return cached;
}

/** Test helper: discard the memoized environment. */
export function resetConfig(): void {
  cached = null;
}
