import type { DatabaseClient } from '#app/infrastructure/database.ts';
import type { Prisma, Task as TaskRow } from '#app/generated/prisma/client.ts';
import { TaskError } from './entity.ts';
import type { Task, TaskFilter } from './entity.ts';
import type { NewTask, TaskChange } from './types.ts';

export class TaskRepository {
  #db: DatabaseClient;

  constructor(db: DatabaseClient) {
    this.#db = db;
  }

  async create({ callId, type, metadata }: NewTask): Promise<Task> {
    try {
      const row = await this.#db.task.create({
        data: { call_id: callId, type, metadata: metadata as Prisma.InputJsonObject },
      });
      return toTask(row);
    } catch (err) {
      if (errorCode(err) === 'P2003') throw new TaskError(400, `Call ${callId} does not exist`);
      throw err;
    }
  }

  async findById(id: string): Promise<Task | null> {
    const row = await this.#db.task.findUnique({ where: { id } });
    return row && toTask(row);
  }

  /** Newest first. */
  async list(filter: TaskFilter): Promise<Task[]> {
    const rows = await this.#db.task.findMany({
      where: {
        ...(filter.callId && { call_id: filter.callId }),
        ...(filter.type && { type: filter.type }),
        ...(filter.status && { status: filter.status }),
      },
      orderBy: { created_at: 'desc' },
    });
    return rows.map(toTask);
  }

  /** The QUEUED or RUNNING task of the call, if it has one. */
  async findUnfinished(callId: string): Promise<Task | null> {
    const row = await this.#db.task.findFirst({
      where: { call_id: callId, status: { in: ['QUEUED', 'RUNNING'] } },
    });
    return row && toTask(row);
  }

  /** Null if there is no such task. */
  async update(id: string, { status, error, startedAt, finishedAt }: TaskChange): Promise<Task | null> {
    try {
      const row = await this.#db.task.update({
        where: { id },
        data: {
          status,
          error,
          ...(startedAt && { started_at: startedAt }),
          ...(finishedAt && { finished_at: finishedAt }),
        },
      });
      return toTask(row);
    } catch (err) {
      if (errorCode(err) === 'P2025') return null;
      throw err;
    }
  }
}

function toTask(row: TaskRow): Task {
  return {
    id: row.id,
    callId: row.call_id,
    type: row.type,
    status: row.status,
    metadata: row.metadata as Record<string, unknown>,
    error: row.error,
    startedAt: row.started_at?.toISOString() ?? null,
    finishedAt: row.finished_at?.toISOString() ?? null,
    createdAt: row.created_at.toISOString(),
    updatedAt: row.updated_at.toISOString(),
  };
}

// https://www.prisma.io/docs/orm/reference/error-reference
function errorCode(err: unknown): string | undefined {
  return (err as { code?: string }).code;
}
