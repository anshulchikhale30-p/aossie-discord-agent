import { and, eq } from "drizzle-orm";
import { defineDynamic, defineInstructions } from "eve/instructions";
import { readScope } from "../../src/auth/scope.js";
import { bots } from "../../src/db/schema.js";
import { getDatabase } from "../../src/runtime.js";

/**
 * Appends the provider-managed prompt stored on the bot record. The dashboard
 * will own this field; the static safety and workflow rules stay in
 * `agent/instructions.md`.
 */
export default defineDynamic(async (ctx) => {
  const auth = ctx.session.auth.current;
  if (!auth) return null;

  let scope;
  try {
    scope = readScope(auth);
  } catch {
    return null;
  }

  const prompt = await ctx.memo(
    ["provider-system-prompt", scope.tenantId, scope.botId, ctx.turn?.id ?? null],
    async () => {
      const rows = await getDatabase()
        .select({ systemPrompt: bots.systemPrompt })
        .from(bots)
        .where(
          and(
            eq(bots.tenantId, scope.tenantId),
            eq(bots.id, scope.botId),
          ),
        )
        .limit(1);
      return rows[0]?.systemPrompt ?? null;
    },
  );

  if (!prompt) return null;

  return defineInstructions({
    content: `## Provider-specific instructions\n\n${prompt}`,
    role: "system",
  });
});
