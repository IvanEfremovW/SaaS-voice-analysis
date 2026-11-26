import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import type { DatabaseClient } from '#app/infrastructure/database.ts';
import { TaskError } from '#app/modules/data/task/entity.ts';
import { TaskRepository } from '#app/modules/data/task/repository.ts';

const row = {
  id: 't1',
  call_id: 'c1',
  type: 'TRANSCRIPTION',
  status: 'RUNNING',
  metadata: { variantId: 'vad_5s' },
  error: null,
  started_at: new Date('2026-11-01T10:01:00Z'),
  finished_at: null,
  created_at: new Date('2026-11-01T10:00:00Z'),
  updated_at: new Date('2026-11-01T10:01:00Z'),
};

const prismaError = (code: string) => Object.assign(new Error(code), { code });

/** A database client whose task table answers with `task`. */
const fakeDb = (task: Record<string, (...args: unknown[]) => Promise<unknown>>) => ({ task }) as unknown as DatabaseClient;

describe('TaskRepository', () => {
  it('maps a row to a Task', async () => {
    const repo = new TaskRepository(fakeDb({ findUnique: async () => row }));
    assert.deepEqual(await repo.findById('t1'), {
      id: 't1',
      callId: 'c1',
      type: 'TRANSCRIPTION',
      status: 'RUNNING',
      metadata: { variantId: 'vad_5s' },
      error: null,
      startedAt: '2026-11-01T10:01:00.000Z',
      finishedAt: null,
      createdAt: '2026-11-01T10:00:00.000Z',
      updatedAt: '2026-11-01T10:01:00.000Z',
    });
  });

  it('looks for an unfinished task among QUEUED and RUNNING ones', async () => {
    const queries: unknown[] = [];
    const repo = new TaskRepository(fakeDb({ findFirst: async (args) => (queries.push(args), null) }));
    assert.equal(await repo.findUnfinished('c1'), null);
    assert.deepEqual(queries, [{ where: { call_id: 'c1', status: { in: ['QUEUED', 'RUNNING'] } } }]);
  });

  it('writes only the timestamps that are given', async () => {
    const updates: unknown[] = [];
    const repo = new TaskRepository(fakeDb({ update: async (args) => (updates.push(args), row) }));
    const finishedAt = new Date('2026-11-01T10:05:00Z');
    await repo.update('t1', { status: 'SUCCEEDED', error: null, finishedAt });
    assert.deepEqual(updates, [{ where: { id: 't1' }, data: { status: 'SUCCEEDED', error: null, finished_at: finishedAt } }]);
  });

  it('returns null for a missing task, and 400 for a missing call', async () => {
    const repo = new TaskRepository(
      fakeDb({
        update: async () => Promise.reject(prismaError('P2025')),
        create: async () => Promise.reject(prismaError('P2003')),
      }),
    );
    assert.equal(await repo.update('nope', { status: 'RUNNING', error: null }), null);
    await assert.rejects(
      repo.create({ callId: 'nope', type: 'TRANSCRIPTION', metadata: {} }),
      (err: unknown) => err instanceof TaskError && err.status === 400,
    );
  });
});
