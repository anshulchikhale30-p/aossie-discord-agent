import type { Platform } from "../db/schema.js";

/**
 * Auth attributes are the only trusted tenant/bot scope a tool receives. The
 * model never chooses them; the Chat SDK channel derives them from the
 * verified adapter event and the application connection record.
 */
export const AUTH_ATTR = {
  tenantId: "frontdesk.tenant_id",
  botId: "frontdesk.bot_id",
  connectionId: "frontdesk.connection_id",
  conversationId: "frontdesk.conversation_id",
  platform: "frontdesk.platform",
  externalUserId: "frontdesk.external_user_id",
  externalThreadId: "frontdesk.external_thread_id",
  role: "frontdesk.role",
  displayName: "frontdesk.display_name",
} as const;

export type FrontdeskRole = "customer" | "maintainer";

export interface AuthLike {
  readonly authenticator: string;
  readonly principalId: string;
  readonly principalType: string;
  readonly attributes: Readonly<Record<string, string | readonly string[]>>;
}

export interface RequestScope {
  tenantId: string;
  botId: string;
  connectionId: string;
  conversationId: string;
  platform: Platform;
  externalUserId: string;
  externalThreadId: string;
  role: FrontdeskRole;
  displayName: string | null;
}

export class MissingAuthScopeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MissingAuthScopeError";
  }
}

function attribute(auth: AuthLike, key: string): string | null {
  const value = auth.attributes[key];
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return (value as readonly string[])[0] ?? null;
  return null;
}

export function readScope(auth: AuthLike | null | undefined): RequestScope {
  if (!auth) {
    throw new MissingAuthScopeError(
      "This tool needs an authenticated front-desk session. Start the request through the Chat SDK channel.",
    );
  }

  const tenantId = attribute(auth, AUTH_ATTR.tenantId);
  const botId = attribute(auth, AUTH_ATTR.botId);
  const connectionId = attribute(auth, AUTH_ATTR.connectionId);
  const conversationId = attribute(auth, AUTH_ATTR.conversationId);
  const platform = attribute(auth, AUTH_ATTR.platform);
  const externalUserId = attribute(auth, AUTH_ATTR.externalUserId);
  const externalThreadId = attribute(auth, AUTH_ATTR.externalThreadId);
  const role = attribute(auth, AUTH_ATTR.role);

  if (
    !tenantId ||
    !botId ||
    !connectionId ||
    !conversationId ||
    !platform ||
    !externalUserId ||
    !externalThreadId ||
    !role
  ) {
    throw new MissingAuthScopeError(
      "The front-desk session is missing its tenant, bot, connection, conversation, user, thread, or role scope.",
    );
  }

  if (platform !== "discord" && platform !== "whatsapp") {
    throw new MissingAuthScopeError(`Unsupported platform scope: ${platform}`);
  }
  if (role !== "customer" && role !== "maintainer") {
    throw new MissingAuthScopeError(`Unsupported role scope: ${role}`);
  }

  return {
    tenantId,
    botId,
    connectionId,
    conversationId,
    platform,
    externalUserId,
    externalThreadId,
    role,
    displayName: attribute(auth, AUTH_ATTR.displayName),
  };
}

export function tryReadScope(
  auth: AuthLike | null | undefined,
): RequestScope | null {
  try {
    return readScope(auth);
  } catch {
    return null;
  }
}

export function assertMaintainer(scope: RequestScope): void {
  if (scope.role !== "maintainer") {
    throw new Error(
      "This operation is available only in the provider maintainer channel.",
    );
  }
}

export function assertCustomer(scope: RequestScope): void {
  if (scope.role !== "customer") {
    throw new Error(
      "This operation is available only in a customer conversation.",
    );
  }
}

export interface BuildAuthInput {
  tenantId: string;
  botId: string;
  connectionId: string;
  conversationId: string;
  platform: Platform;
  externalUserId: string;
  externalThreadId: string;
  role: FrontdeskRole;
  displayName?: string | null;
}

export function buildSessionAuth(input: BuildAuthInput): AuthLike {
  const attributes: Record<string, string> = {
    [AUTH_ATTR.tenantId]: input.tenantId,
    [AUTH_ATTR.botId]: input.botId,
    [AUTH_ATTR.connectionId]: input.connectionId,
    [AUTH_ATTR.conversationId]: input.conversationId,
    [AUTH_ATTR.platform]: input.platform,
    [AUTH_ATTR.externalUserId]: input.externalUserId,
    [AUTH_ATTR.externalThreadId]: input.externalThreadId,
    [AUTH_ATTR.role]: input.role,
  };
  if (input.displayName) {
    attributes[AUTH_ATTR.displayName] = input.displayName;
  }

  return {
    authenticator: input.platform,
    principalType: input.role,
    principalId: input.externalUserId,
    attributes,
  };
}
