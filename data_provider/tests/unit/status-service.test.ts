import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { describe, it } from 'node:test';
import type { DatabaseClient } from '#app/infrastructure/database.ts';
import { StatusError } from '#app/modules/data/status/entity.ts';
import type { CallStatus, Status, UpdateStatusInput } from '#app/modules/data/status/entity.ts';
import { StatusRepository } from '#app/modules/data/status/repository.ts';
import { StatusService } from '#app/modules/data/status/service.ts';

class FakeStatusRepository extends StatusRepository {
  statuses = new Map<string, Status>();

  constructor() {
    super({} as DatabaseClient);
  }

  override async create(value: CallStatus): Promise<Status> {
    const now = new Date().toISOString();
    const status: Status = { id: randomUUID(), value, error: null, createdAt: now, updatedAt: now };
    this.statuses.set(status.id, status);
    return status;
  }

  override async findById(id: string) {
    return this.statuses.get(id) ?? null;
  }

  override async list(value?: CallStatus) {
    return [...this.statuses.values()].filter((s) => !value || s.value === value);
  }

  override async update(id: string, value: CallStatus, error: string | null) {
    const status = this.statuses.get(id);
    if (!status) return null;
    const updated = { ...status, value, error };
    this.statuses.set(id, updated);
    return updated;
  }

  override async delete(id: string) {
    return this.statuses.delete(id);
  }
}

const isStatusError = (status: number) => (err: unknown) => err instanceof StatusError && err.status === status;

describe('StatusService', () => {
  it('creates UPLOADED by default', async () => {
    const status = await new StatusService(new FakeStatusRepository()).create();
    assert.equal(status.value, 'UPLOADED');
    assert.equal(status.error, null);
  });

  it('moves a status to the next stage', async () => {
    const service = new StatusService(new FakeStatusRepository());
    const { id } = await service.create();
    assert.equal((await service.update(id, { value: 'TRANSCRIBING' })).value, 'TRANSCRIBING');
  });

  it('requires an error for FAILED and clears it on the next value', async () => {
    const service = new StatusService(new FakeStatusRepository());
    const { id } = await service.create();

    await assert.rejects(service.update(id, { value: 'FAILED' }), isStatusError(400));
    const failed = await service.update(id, { value: 'FAILED', error: ' STT timeout ' });
    assert.equal(failed.error, 'STT timeout');

    const retried = await service.update(id, { value: 'TRANSCRIBING' });
    assert.equal(retried.error, null);
  });

  it('rejects unknown values and an error without FAILED', async () => {
    const service = new StatusService(new FakeStatusRepository());
    const { id } = await service.create();
    await assert.rejects(service.create('DONE' as CallStatus), isStatusError(400));
    await assert.rejects(service.update(id, { value: 'DONE' } as unknown as UpdateStatusInput), isStatusError(400));
    await assert.rejects(service.update(id, { value: 'ANALYZED', error: 'x' }), isStatusError(400));
    await assert.rejects(service.update(id, null as unknown as UpdateStatusInput), isStatusError(400));
    await assert.rejects(service.list('DONE' as CallStatus), isStatusError(400));
  });

  it('answers 404 for an unknown status', async () => {
    const service = new StatusService(new FakeStatusRepository());
    await assert.rejects(service.get('nope'), isStatusError(404));
    await assert.rejects(service.update('nope', { value: 'ANALYZED' }), isStatusError(404));
    await assert.rejects(service.delete('nope'), isStatusError(404));
  });
});
