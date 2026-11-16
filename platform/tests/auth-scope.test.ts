import { describe, expect, it } from "vitest";
import {
  AUTH_ATTR,
  MissingAuthScopeError,
  assertCustomer,
  assertMaintainer,
  buildSessionAuth,
  readScope,
  tryReadScope,
} from "../src/auth/scope.js";

const input = {
  tenantId: "tenant-1",
  botId: "bot-1",
  connectionId: "connection-1",
  conversationId: "conversation-1",
  platform: "discord" as const,
  externalUserId: "customer-1",
  externalThreadId: "discord:guild-1:channel-1",
  role: "customer" as const,
  displayName: "Ada",
};

describe("trusted auth scope", () => {
  it("round-trips a built session auth", () => {
    const auth = buildSessionAuth(input);
    const scope = readScope(auth);

    expect(scope).toEqual(input);
    expect(auth.principalId).toBe("customer-1");
    expect(auth.principalType).toBe("customer");
    expect(auth.authenticator).toBe("discord");
  });

  it("rejects a session without auth or with incomplete attributes", () => {
    expect(() => readScope(null)).toThrow(MissingAuthScopeError);
    expect(() => readScope(undefined)).toThrow(MissingAuthScopeError);

    const auth = buildSessionAuth(input);
    const attributes = { ...auth.attributes };
    delete (attributes as Record<string, string>)[AUTH_ATTR.conversationId];

    expect(() =>
      readScope({ ...auth, attributes }),
    ).toThrow(/missing its tenant, bot, connection, conversation/i);
  });

  it("rejects unsupported platform and role values", () => {
    const auth = buildSessionAuth(input);

    expect(() =>
      readScope({
        ...auth,
        attributes: { ...auth.attributes, [AUTH_ATTR.platform]: "slack" },
      }),
    ).toThrow(/Unsupported platform/i);

    expect(() =>
      readScope({
        ...auth,
        attributes: { ...auth.attributes, [AUTH_ATTR.role]: "admin" },
      }),
    ).toThrow(/Unsupported role/i);
  });

  it("returns null from tryReadScope instead of throwing", () => {
    expect(tryReadScope(null)).toBeNull();
    expect(tryReadScope(buildSessionAuth(input))?.conversationId).toBe(
      "conversation-1",
    );
  });

  it("asserts the maintainer and customer roles", () => {
    const customer = readScope(buildSessionAuth(input));
    const maintainer = readScope(
      buildSessionAuth({ ...input, role: "maintainer" }),
    );

    expect(() => assertMaintainer(customer)).toThrow(/maintainer channel/i);
    expect(() => assertCustomer(maintainer)).toThrow(/customer conversation/i);
    expect(() => assertMaintainer(maintainer)).not.toThrow();
    expect(() => assertCustomer(customer)).not.toThrow();
  });

  it("uses the first value when an adapter supplies an attribute array", () => {
    const auth = buildSessionAuth(input);
    const scope = readScope({
      ...auth,
      attributes: {
        ...auth.attributes,
        [AUTH_ATTR.displayName]: ["Ada", "Ada Lovelace"],
      },
    });
    expect(scope.displayName).toBe("Ada");
  });
});
