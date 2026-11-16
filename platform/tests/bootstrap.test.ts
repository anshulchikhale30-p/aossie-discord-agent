import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  connectionSeedsFromConfig,
  ensureBootstrap,
} from "../src/db/bootstrap.js";
import {
  createTestDatabase,
  testConfig,
  type TestDatabase,
} from "./helpers.js";

describe("single-tenant bootstrap", () => {
  let handle: TestDatabase;

  beforeAll(async () => {
    handle = await createTestDatabase();
  });

  afterAll(async () => {
    await handle.close();
  });

  it("is idempotent and updates managed fields", async () => {
    const config = testConfig();
    const first = await ensureBootstrap(handle.db, config);
    const second = await ensureBootstrap(handle.db, config);

    expect(second.tenant.id).toBe(first.tenant.id);
    expect(second.bot.id).toBe(first.bot.id);
    expect(second.connections.map((row) => row.id).sort()).toEqual(
      first.connections.map((row) => row.id).sort(),
    );
    expect(first.connections).toHaveLength(1);

    const updated = await ensureBootstrap(handle.db, {
      ...config,
      tenantName: "Renamed Tenant",
      botName: "Renamed Bot",
      botSystemPrompt: "Always answer in English.",
      discord: config.discord
        ? {
            ...config.discord,
            maintainerChannelId: "discord:guild-9:new-maintainer",
            maintainerChannelKey: "new-maintainer",
          }
        : null,
    });

    expect(updated.tenant.id).toBe(first.tenant.id);
    expect(updated.tenant.name).toBe("Renamed Tenant");
    expect(updated.bot.id).toBe(first.bot.id);
    expect(updated.bot.name).toBe("Renamed Bot");
    expect(updated.bot.systemPrompt).toBe("Always answer in English.");
    expect(updated.connections[0]?.id).toBe(first.connections[0]?.id);
    expect(updated.connections[0]?.maintainerChannelId).toBe(
      "discord:guild-9:new-maintainer",
    );
  });

  it("creates one connection per configured platform", async () => {
    const config = testConfig({
      tenantSlug: "two-platform-tenant",
      whatsapp: {
        accessToken: "whatsapp-token",
        appSecret: "whatsapp-secret",
        phoneNumberId: "phone-1",
        verifyToken: "verify",
      },
    });

    const result = await ensureBootstrap(handle.db, config);
    expect(result.connections.map((row) => row.platform).sort()).toEqual([
      "discord",
      "whatsapp",
    ]);

    const seeds = connectionSeedsFromConfig(config);
    expect(seeds).toHaveLength(2);
    expect(seeds.find((seed) => seed.platform === "whatsapp")).toMatchObject({
      externalId: "phone-1",
      maintainerChannelId: null,
    });

    const repeated = await ensureBootstrap(handle.db, config);
    expect(repeated.connections.map((row) => row.id).sort()).toEqual(
      result.connections.map((row) => row.id).sort(),
    );
  });

  it("skips platforms whose credentials are incomplete", () => {
    const seeds = connectionSeedsFromConfig(
      testConfig({ discord: null, whatsapp: null }),
    );
    expect(seeds).toEqual([]);
  });
});
