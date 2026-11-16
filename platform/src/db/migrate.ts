import { fileURLToPath } from "node:url";
import { migrate } from "drizzle-orm/postgres-js/migrator";
import { getConfig } from "../config.js";
import { createDatabase } from "./client.js";

const migrationsFolder = fileURLToPath(new URL("../../drizzle", import.meta.url));

const handle = createDatabase(getConfig().databaseUrl, { max: 1 });

try {
  await migrate(handle.db as never, { migrationsFolder });
  console.log(`Applied database migrations from ${migrationsFolder}`);
} finally {
  await handle.close();
}
