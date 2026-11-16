import { getConfig, type AppConfig } from "./config.js";
import { ensureBootstrap, type BootstrapResult } from "./db/bootstrap.js";
import { createDatabase, type Database, type DatabaseHandle } from "./db/client.js";

let handle: DatabaseHandle | null = null;
let bootstrapPromise: Promise<BootstrapResult> | null = null;

/** Process-wide database handle for tools, channels, and scripts. */
export function getDatabase(): Database {
  handle ??= createDatabase(getConfig().databaseUrl);
  return handle.db;
}

/** Process-wide tenant/bot/connection bootstrap, run at most once. */
export function ensureRuntimeBootstrap(): Promise<BootstrapResult> {
  bootstrapPromise ??= ensureBootstrap(getDatabase(), getConfig());
  return bootstrapPromise;
}

export function getRuntimeConfig(): AppConfig {
  return getConfig();
}

export async function closeRuntime(): Promise<void> {
  bootstrapPromise = null;
  if (handle) {
    await handle.close();
    handle = null;
  }
}
