import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import type { DatabaseClient } from '#app/infrastructure/database.ts';
import { TranscriptionError } from '#app/modules/data/transcription/entity.ts';
import { TranscriptionRepository } from '#app/modules/data/transcription/repository.ts';

const row = {
  id: 't1',
  call_id: 'c1',
  file_id: 'f1',
  created_at: new Date('2026-11-01T10:00:00Z'),
  updated_at: new Date('2026-11-01T10:00:00Z'),
};

const prismaError = (code: string) => Object.assign(new Error(code), { code });

const fakeDb = (transcription: Record<string, (...args: unknown[]) => Promise<unknown>>) =>
  ({ transcription }) as unknown as DatabaseClient;

const isError = (status: number) => (err: unknown) => err instanceof TranscriptionError && err.status === status;

describe('TranscriptionRepository', () => {
  it('maps a row to a Transcription', async () => {
    const repo = new TranscriptionRepository(fakeDb({ findUnique: async () => row }));
    assert.deepEqual(await repo.findById('t1'), {
      id: 't1',
      callId: 'c1',
      fileId: 'f1',
      createdAt: '2026-11-01T10:00:00.000Z',
      updatedAt: '2026-11-01T10:00:00.000Z',
    });
  });

  it('reports a missing call as 400 and a taken call or file as 409', async () => {
    const missingCall = new TranscriptionRepository(fakeDb({ create: async () => Promise.reject(prismaError('P2003')) }));
    await assert.rejects(missingCall.create({ callId: 'nope', fileId: 'f1' }), isError(400));

    const taken = new TranscriptionRepository(fakeDb({ create: async () => Promise.reject(prismaError('P2002')) }));
    await assert.rejects(taken.create({ callId: 'c1', fileId: 'f1' }), isError(409));
  });

  it('returns false when deleting a missing transcription', async () => {
    const repo = new TranscriptionRepository(fakeDb({ delete: async () => Promise.reject(prismaError('P2025')) }));
    assert.equal(await repo.delete('nope'), false);
  });
});
