import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import type { DatabaseClient } from '#app/infrastructure/database.ts';
import { CallError } from '#app/modules/data/call/entity.ts';
import { CallRepository } from '#app/modules/data/call/repository.ts';

const row = {
  id: 'c1',
  user_id: 'u1',
  client_phone: '+79001234567',
  direction: 'INCOMING',
  started_at: new Date('2026-11-01T06:00:00Z'),
  duration_sec: 95,
  file_id: 'f1',
  status_id: 's1',
  created_at: new Date('2026-11-01T10:00:00Z'),
  updated_at: new Date('2026-11-01T10:00:00Z'),
  status: {
    id: 's1',
    value: 'UPLOADED',
    error: null,
    created_at: new Date('2026-11-01T10:00:00Z'),
    updated_at: new Date('2026-11-01T10:00:00Z'),
  },
};

const metadata = {
  userId: 'u1',
  clientPhone: '+79001234567',
  direction: 'INCOMING' as const,
  startedAt: '2026-11-01T09:00:00+03:00',
  durationSec: 95,
};

type Fn = (...args: unknown[]) => Promise<unknown>;
const prismaError = (code: string) => Object.assign(new Error(code), { code });
const fakeDb = (call: Record<string, Fn>, status: Record<string, Fn> = {}) =>
  ({ call, status }) as unknown as DatabaseClient;
const isCallError = (status: number) => (err: unknown) => err instanceof CallError && err.status === status;

describe('CallRepository', () => {
  it('maps a row with its status to a Call', async () => {
    const repo = new CallRepository(fakeDb({ findUnique: async () => row }));
    const call = await repo.findById('c1');
    assert.equal(call?.startedAt, '2026-11-01T06:00:00.000Z');
    assert.equal(call?.fileId, 'f1');
    assert.deepEqual(call?.status, {
      id: 's1',
      value: 'UPLOADED',
      error: null,
      createdAt: '2026-11-01T10:00:00.000Z',
      updatedAt: '2026-11-01T10:00:00.000Z',
    });
  });

  it('creates the call with a new UPLOADED status in one write', async () => {
    let args: { data: Record<string, unknown> } | undefined;
    const repo = new CallRepository(
      fakeDb({
        create: async (a) => {
          args = a as typeof args;
          return row;
        },
      }),
    );
    await repo.create(metadata, 'f1');
    assert.deepEqual(args?.data.status, { create: { value: 'UPLOADED' } });
    assert.deepEqual(args?.data.file, { connect: { id: 'f1' } });
    assert.deepEqual(args?.data.user, { connect: { id: 'u1' } });
  });

  it('reports a missing user as 400 and a recording used twice as 409', async () => {
    const missingUser = new CallRepository(fakeDb({ create: async () => Promise.reject(prismaError('P2025')) }));
    await assert.rejects(missingUser.create(metadata, 'f1'), isCallError(400));

    const taken = new CallRepository(fakeDb({ create: async () => Promise.reject(prismaError('P2002')) }));
    await assert.rejects(taken.create(metadata, 'f1'), isCallError(409));
  });

  it('returns null when updating a missing call, 400 when the new user is missing', async () => {
    const missingCall = new CallRepository(
      fakeDb({ update: async () => Promise.reject(prismaError('P2025')), findUnique: async () => null }),
    );
    assert.equal(await missingCall.update('nope', { durationSec: 1 }), null);

    const missingUser = new CallRepository(
      fakeDb({ update: async () => Promise.reject(prismaError('P2025')), findUnique: async () => row }),
    );
    await assert.rejects(missingUser.update('c1', { userId: 'nope' }), isCallError(400));
  });

  it('deletes the status together with the call', async () => {
    const deleted: string[] = [];
    const repo = new CallRepository(
      fakeDb(
        { delete: async () => row },
        {
          delete: async (a) => {
            deleted.push((a as { where: { id: string } }).where.id);
            return {};
          },
        },
      ),
    );
    assert.equal(await repo.delete('c1'), true);
    assert.deepEqual(deleted, ['s1']);
  });

  it('builds the list filter from userId, status and the period', async () => {
    let where: unknown;
    const repo = new CallRepository(
      fakeDb({
        findMany: async (a) => {
          where = (a as { where: unknown }).where;
          return [];
        },
      }),
    );
    await repo.list({ userId: 'u1', status: 'FAILED', from: '2026-11-01T00:00:00Z' });
    assert.deepEqual(where, {
      user_id: 'u1',
      status: { value: 'FAILED' },
      started_at: { gte: new Date('2026-11-01T00:00:00Z') },
    });
  });
});
