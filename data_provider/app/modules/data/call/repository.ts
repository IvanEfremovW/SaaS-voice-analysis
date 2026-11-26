import type { DatabaseClient } from '#app/infrastructure/database.ts';
import type { Prisma } from '#app/generated/prisma/client.ts';
import { CallError } from './entity.ts';
import type { Call, CallFilter, CallMetadata } from './entity.ts';

type CallRow = Prisma.CallGetPayload<{ include: { status: true } }>;

const include = { status: true } as const;

export class CallRepository {
  #db: DatabaseClient;

  constructor(db: DatabaseClient) {
    this.#db = db;
  }

  /** Creates the call together with its UPLOADED status, atomically (one nested write). */
  async create(metadata: CallMetadata, fileId: string): Promise<Call> {
    try {
      const row = await this.#db.call.create({
        data: {
          client_phone: metadata.clientPhone,
          direction: metadata.direction,
          started_at: new Date(metadata.startedAt),
          duration_sec: metadata.durationSec,
          user: { connect: { id: metadata.userId } },
          file: { connect: { id: fileId } },
          status: { create: { value: 'UPLOADED' } },
        },
        include,
      });
      return toCall(row);
    } catch (err) {
      throw translate(err, metadata.userId);
    }
  }

  async findById(id: string): Promise<Call | null> {
    const row = await this.#db.call.findUnique({ where: { id }, include });
    return row && toCall(row);
  }

  async list(filter: CallFilter): Promise<Call[]> {
    const rows = await this.#db.call.findMany({
      where: {
        ...(filter.userId && { user_id: filter.userId }),
        ...(filter.status && { status: { value: filter.status } }),
        ...((filter.from || filter.to) && {
          started_at: {
            ...(filter.from && { gte: new Date(filter.from) }),
            ...(filter.to && { lt: new Date(filter.to) }),
          },
        }),
      },
      orderBy: { started_at: 'desc' },
      include,
    });
    return rows.map(toCall);
  }

  /** Null if there is no such call. */
  async update(id: string, metadata: Partial<CallMetadata>, fileId?: string): Promise<Call | null> {
    try {
      const row = await this.#db.call.update({
        where: { id },
        data: {
          ...toColumns(metadata),
          ...(metadata.userId && { user: { connect: { id: metadata.userId } } }),
          ...(fileId && { file: { connect: { id: fileId } } }),
        },
        include,
      });
      return toCall(row);
    } catch (err) {
      if (errorCode(err) === 'P2025' && !(await this.findById(id))) return null;
      throw translate(err, metadata.userId);
    }
  }

  /** Deletes the call and its status. False if there is no such call. */
  async delete(id: string): Promise<boolean> {
    try {
      const row = await this.#db.call.delete({ where: { id } });
      await this.#db.status.delete({ where: { id: row.status_id } });
      return true;
    } catch (err) {
      if (errorCode(err) === 'P2025') return false;
      throw err;
    }
  }
}

function toColumns(metadata: Partial<CallMetadata>) {
  return {
    ...(metadata.clientPhone !== undefined && { client_phone: metadata.clientPhone }),
    ...(metadata.direction !== undefined && { direction: metadata.direction }),
    ...(metadata.startedAt !== undefined && { started_at: new Date(metadata.startedAt) }),
    ...(metadata.durationSec !== undefined && { duration_sec: metadata.durationSec }),
  };
}

function toCall(row: CallRow): Call {
  return {
    id: row.id,
    userId: row.user_id,
    clientPhone: row.client_phone,
    direction: row.direction,
    startedAt: row.started_at.toISOString(),
    durationSec: row.duration_sec,
    fileId: row.file_id,
    status: {
      id: row.status.id,
      value: row.status.value,
      error: row.status.error,
      createdAt: row.status.created_at.toISOString(),
      updatedAt: row.status.updated_at.toISOString(),
    },
    createdAt: row.created_at.toISOString(),
    updatedAt: row.updated_at.toISOString(),
  };
}

// https://www.prisma.io/docs/orm/reference/error-reference
function errorCode(err: unknown): string | undefined {
  return (err as { code?: string }).code;
}

function translate(err: unknown, userId: string | undefined): unknown {
  switch (errorCode(err)) {
    // A `connect` to a missing record: the user (the file is created by the service just before).
    case 'P2025':
    case 'P2018':
      return new CallError(400, `User ${userId} does not exist`);
    case 'P2002':
      return new CallError(409, 'This recording already belongs to another call');
    default:
      return err;
  }
}
