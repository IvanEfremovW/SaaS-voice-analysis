import type { DatabaseClient } from '#app/infrastructure/database.ts';
import type { Status as StatusRow } from '#app/generated/prisma/client.ts';
import { StatusError } from './entity.ts';
import type { CallStatus, Status } from './entity.ts';

export class StatusRepository {
  #db: DatabaseClient;

  constructor(db: DatabaseClient) {
    this.#db = db;
  }

  async create(value: CallStatus): Promise<Status> {
    return toStatus(await this.#db.status.create({ data: { value } }));
  }

  async findById(id: string): Promise<Status | null> {
    const row = await this.#db.status.findUnique({ where: { id } });
    return row && toStatus(row);
  }

  async list(value?: CallStatus): Promise<Status[]> {
    const rows = await this.#db.status.findMany({ where: value ? { value } : {}, orderBy: { updated_at: 'desc' } });
    return rows.map(toStatus);
  }

  /** Null if there is no such status. */
  async update(id: string, value: CallStatus, error: string | null): Promise<Status | null> {
    try {
      return toStatus(await this.#db.status.update({ where: { id }, data: { value, error } }));
    } catch (err) {
      if (errorCode(err) === 'P2025') return null;
      throw err;
    }
  }

  /** False if there is no such status. */
  async delete(id: string): Promise<boolean> {
    try {
      await this.#db.status.delete({ where: { id } });
      return true;
    } catch (err) {
      if (errorCode(err) === 'P2025') return false;
      if (errorCode(err) === 'P2003') throw new StatusError(409, 'The status belongs to a call');
      throw err;
    }
  }
}

function toStatus(row: StatusRow): Status {
  return {
    id: row.id,
    value: row.value,
    error: row.error,
    createdAt: row.created_at.toISOString(),
    updatedAt: row.updated_at.toISOString(),
  };
}

// https://www.prisma.io/docs/orm/reference/error-reference
function errorCode(err: unknown): string | undefined {
  return (err as { code?: string }).code;
}
