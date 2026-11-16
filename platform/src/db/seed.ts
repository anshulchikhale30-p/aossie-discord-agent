import { getConfig } from "../config.js";
import { ensureBootstrap } from "./bootstrap.js";
import { createDatabase } from "./client.js";

const config = getConfig();
const handle = createDatabase(config.databaseUrl, { max: 1 });

try {
  const result = await ensureBootstrap(handle.db, config);
  console.log(
    [
      `Seeded tenant ${result.tenant.slug} (${result.tenant.id})`,
      `bot ${result.bot.slug} (${result.bot.id})`,
      `${result.connections.length} connection(s)`,
    ].join(", "),
  );
} finally {
  await handle.close();
}
