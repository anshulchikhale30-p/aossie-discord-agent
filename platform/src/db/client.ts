import type { PgDatabase, PgQueryResultHKT } from "drizzle-orm/pg-core";
import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import * as schema from "./schema.js";

/**
 * The repository layer only needs the portable PostgreSQL surface, so tests can
 * pass a PGlite database while production passes a postgres-js database.
 */
export type Database = PgDatabase<PgQueryResultHKT, typeof schema>;

export interface DatabaseHandle {
  db: Database;
  client: postgres.Sql;
  close(): Promise<void>;
}

export interface CreateDatabaseOptions {
  max?: number;
  idleTimeoutSeconds?: number;
}

export function createDatabase(
  url: string,
  options: CreateDatabaseOptions = {},
): DatabaseHandle {
  const client = postgres(url, {
    max: options.max ?? 10,
    idle_timeout: options.idleTimeoutSeconds ?? 30,
    onnotice: () => undefined,
  });
  const db = drizzle(client, { schema }) as unknown as Database;

  return {
    db,
    client,
    async close() {
      await client.end({ timeout: 5 });
    },
  };
}
