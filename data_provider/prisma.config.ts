import { defineConfig } from 'prisma/config';

// Prisma 7 no longer reads .env by itself; in Docker the variables come from the environment.
try {
  process.loadEnvFile();
} catch {}

export default defineConfig({
  // The folder, so every .prisma file in it is part of the schema.
  schema: 'prisma',
  datasource: {
    url: process.env.DATABASE_URL ?? '',
  },
});
