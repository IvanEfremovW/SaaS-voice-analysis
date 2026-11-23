import { PrismaPg } from '@prisma/adapter-pg';
import { config } from '#app/config.ts';
import { PrismaClient } from '#app/generated/prisma/client.ts';
import type { Prisma } from '#app/generated/prisma/client.ts';

/**
 * What repositories take in their constructor. Both the client and a transaction
 * (inside database.$transaction) fit, so several repositories can write in one transaction.
 */
export type DatabaseClient = Prisma.TransactionClient;

export function createDatabase(url: string): PrismaClient {
  return new PrismaClient({ adapter: new PrismaPg({ connectionString: url }) });
}

/** One client per process: it holds the connection pool. It connects on the first query. */
export const database = createDatabase(config.databaseUrl);
