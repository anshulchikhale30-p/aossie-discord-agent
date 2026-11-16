import { randomUUID } from "node:crypto";
import type { Database } from "../client.js";
import { auditEvents, type ActorType, type AuditEvent } from "../schema.js";

export interface RecordAuditEventInput {
  tenantId: string;
  botId: string;
  actorType: ActorType;
  actorExternalId?: string | null;
  action: string;
  subjectType?: string | null;
  subjectId?: string | null;
  data?: Record<string, unknown>;
}

export async function recordAuditEvent(
  db: Database,
  input: RecordAuditEventInput,
): Promise<AuditEvent> {
  const inserted = await db
    .insert(auditEvents)
    .values({
      id: randomUUID(),
      tenantId: input.tenantId,
      botId: input.botId,
      actorType: input.actorType,
      actorExternalId: input.actorExternalId ?? null,
      action: input.action,
      subjectType: input.subjectType ?? null,
      subjectId: input.subjectId ?? null,
      data: input.data ?? {},
    })
    .returning();
  return inserted[0]!;
}
