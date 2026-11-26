import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { DataProvider } from '#backend/infrastructure/data-provider.ts';
import { HttpError } from '#backend/infrastructure/http.ts';
import { CallClient } from '#backend/modules/call/client.ts';
import type { CallStatus } from '#backend/modules/call/entity.ts';
import { CallService } from '#backend/modules/call/service.ts';
import type { ProviderCall, ProviderCallFilter, ProviderFile, ProviderTranscription } from '#backend/modules/call/types.ts';
import { UserClient } from '#backend/modules/user/client.ts';
import { UserService } from '#backend/modules/user/service.ts';
import type { ProviderUser } from '#backend/modules/user/types.ts';

const dataProvider = new DataProvider('http://data-provider');

function providerCall(fields: Partial<ProviderCall>): ProviderCall {
  return {
    id: 'c1',
    userId: 'u1',
    clientPhone: '+79001234567',
    direction: 'INCOMING',
    startedAt: '2026-11-01T06:00:00.000Z',
    durationSec: 95,
    fileId: 'f1',
    status: { value: 'TRANSCRIBED', error: null },
    ...fields,
  };
}

class FakeCallClient extends CallClient {
  calls = [
    providerCall({ id: 'c1', userId: 'u1', startedAt: '2026-11-03T06:00:00.000Z', durationSec: 95 }),
    providerCall({ id: 'c2', userId: 'u2', startedAt: '2026-11-02T06:00:00.000Z', durationSec: 30, direction: 'OUTGOING' }),
    providerCall({ id: 'c3', userId: 'gone', startedAt: '2026-11-01T06:00:00.000Z', durationSec: 60 }),
  ];
  transcription: ProviderTranscription | null = { id: 't1', callId: 'c1', fileId: 'f2', createdAt: '2026-11-04T00:00:00.000Z' };
  filters: ProviderCallFilter[] = [];
  log: string[] = [];

  constructor() {
    super(dataProvider);
  }
  override async list(filter: ProviderCallFilter): Promise<ProviderCall[]> {
    this.filters.push(filter);
    return this.calls;
  }
  override async get(id: string): Promise<ProviderCall> {
    return this.calls.find((call) => call.id === id)!;
  }
  override async getFile(id: string): Promise<ProviderFile> {
    return { id, name: `${id}.wav`, sizeBytes: 100 };
  }
  override async findTranscription(): Promise<ProviderTranscription | null> {
    return this.transcription;
  }
  override async deleteTranscription(id: string): Promise<void> {
    this.log.push(`delete transcription ${id}`);
  }
  override async setStatus(callId: string, value: CallStatus): Promise<void> {
    this.log.push(`status of ${callId}: ${value}`);
  }
}

class FakeUserClient extends UserClient {
  users: ProviderUser[] = [
    { id: 'u1', name: 'Анна', email: 'anna@example.com', role: 'ADMIN' },
    { id: 'u2', name: 'Борис', email: 'boris@example.com', role: 'USER' },
  ];
  constructor() {
    super(dataProvider);
  }
  override async list(): Promise<ProviderUser[]> {
    return this.users;
  }
  override async get(id: string): Promise<ProviderUser> {
    return this.users.find((user) => user.id === id)!;
  }
}

function setup() {
  const calls = new FakeCallClient();
  const service = new CallService(calls, new UserService(new FakeUserClient(), 'anna@example.com'));
  return { calls, service };
}

describe('CallService.list', () => {
  it('adds the names of the employees, newest call first', async () => {
    const { calls, service } = setup();
    const list = await service.list({ userId: 'u1', from: '2026-11-01T00:00:00.000Z' });

    assert.deepEqual(calls.filters, [{ userId: 'u1', from: '2026-11-01T00:00:00.000Z', to: undefined }]);
    assert.deepEqual(
      list.map((call) => [call.id, call.userName]),
      [
        ['c1', 'Анна'],
        ['c2', 'Борис'],
        ['c3', '—'],
      ],
    );
    assert.deepEqual(list[0], {
      id: 'c1',
      userId: 'u1',
      userName: 'Анна',
      clientPhone: '+79001234567',
      direction: 'INCOMING',
      startedAt: '2026-11-03T06:00:00.000Z',
      durationSec: 95,
      status: 'TRANSCRIBED',
      error: null,
    });
  });

  it('filters by direction and sorts by the given column', async () => {
    const { service } = setup();
    const incoming = await service.list({ direction: 'INCOMING', sort: 'durationSec', order: 'asc' });
    assert.deepEqual(
      incoming.map((call) => call.id),
      ['c3', 'c1'],
    );

    const byName = await service.list({ sort: 'userName', order: 'desc' });
    assert.deepEqual(
      byName.map((call) => call.userName),
      ['Борис', 'Анна', '—'],
    );
  });

  it('refuses an unknown sort, order or direction', async () => {
    const { service } = setup();
    for (const query of [{ sort: 'fileId' }, { order: 'up' }, { direction: 'SIDEWAYS' }]) {
      await assert.rejects(service.list(query as never), (err: HttpError) => err.status === 400);
    }
  });
});

describe('CallService.get', () => {
  it('gives the call with its recording and transcription', async () => {
    const { calls, service } = setup();
    const call = await service.get('c1');
    assert.equal(call.userName, 'Анна');
    assert.deepEqual(call.recording, { name: 'f1.wav', sizeBytes: 100 });
    assert.deepEqual(call.transcription, { createdAt: '2026-11-04T00:00:00.000Z', file: { name: 'f2.wav', sizeBytes: 100 } });

    calls.transcription = null;
    assert.equal((await service.get('c1')).transcription, null);
  });
});

describe('CallService.requestTranscription', () => {
  it('deletes the old transcription and sets the call back to UPLOADED', async () => {
    const { calls, service } = setup();
    await service.requestTranscription('c1');
    assert.deepEqual(calls.log, ['delete transcription t1', 'status of c1: UPLOADED']);
  });

  it('refuses while a worker is busy with the call', async () => {
    const { calls, service } = setup();
    calls.calls[0] = providerCall({ status: { value: 'TRANSCRIBING', error: null } });
    await assert.rejects(service.requestTranscription('c1'), (err: HttpError) => err.status === 409);
    assert.deepEqual(calls.log, []);
  });

  it('refuses to download a transcription the call does not have', async () => {
    const { calls, service } = setup();
    calls.transcription = null;
    await assert.rejects(service.downloadTranscription('c1'), (err: HttpError) => err.status === 404);
  });
});
