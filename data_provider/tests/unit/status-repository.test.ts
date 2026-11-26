import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import type { DatabaseClient } from '#app/infrastructure/database.ts';
import { StatusError } from '#app/modules/data/status/entity.ts';
import { StatusRepository } from '#app/modules/data/status/repository.ts';

const row = {
  id: 's1',
  value: 'FAILED',
  error: 'STT timeout',
  created_at: new Date('2026-11-01T10:00:00Z'),
  updated_at: new Date('2026-11-01T10:05:00Z'),
};

const prismaError = (code: string) => Object.assign(new Error(code), { code });

const fakeDb = (status: Record<string, (...args: unknown[]) => Promise<unknown>>) =>
  ({ status }) as unknown as DatabaseClient;

describe('StatusRepository', () => {
  it('maps a row to a Status', async () => {
    const repo = new StatusRepository(fakeDb({ findUnique: async () => row }));
    assert.deepEqual(await repo.findById('s1'), {
      id: 's1',
      value: 'FAILED',
      error: 'STT timeout',
      createdAt: '2026-11-01T10:00:00.000Z',
      updatedAt: '2026-11-01T10:05:00.000Z',
    });
  });

  it('returns null / false for a missing status on update and delete', async () => {
    const missing = async () => Promise.reject(prismaError('P2025'));
    const repo = new StatusRepository(fakeDb({ update: missing, delete: missing }));
    assert.equal(await repo.update('nope', 'ANALYZED', null), null);
    assert.equal(await repo.delete('nope'), false);
  });

  it('refuses to delete the status of a call', async () => {
    const repo = new StatusRepository(fakeDb({ delete: async () => Promise.reject(prismaError('P2003')) }));
    await assert.rejects(repo.delete('s1'), (err) => err instanceof StatusError && err.status === 409);
  });
});
