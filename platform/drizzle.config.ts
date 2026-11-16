import { defineConfig } from "drizzle-kit";

export default defineConfig({
  dialect: "postgresql",
  schema: "./src/db/schema.ts",
  out: "./drizzle",
  dbCredentials: {
    url:
      process.env.DATABASE_URL ??
      "postgres://frontdesk:frontdesk@localhost:5432/frontdesk",
  },
  strict: true,
  verbose: true,
});
