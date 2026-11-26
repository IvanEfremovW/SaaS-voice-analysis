import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import type { DatabaseClient } from '#app/infrastructure/database.ts';
import { CallError } from '#app/modules/data/call/entity.ts';
import type { Call } from '#app/modules/data/call/entity.ts';
import { CallService } from '#app/modules/data/call/service.ts';
import type { Status, UpdateStatusInput } from '#app/modules/data/status/entity.ts';
import { TaskError } from '#app/modules/data/task/entity.ts';
import type { CreateTaskInput, Task, UpdateTaskInput } from '#app/modules/data/task/entity.ts';
import { TaskRepository } from '#app/modules/data/task/repository.ts';
import { TaskService } from '#app/modules/data/task/service.ts';
import type { NewTask, TaskChange } from '#app/modules/data/task/types.ts';
import type { Transcription } from '#app/modules/data/transcription/entity.ts';
import { TranscriptionService } from '#app/modules/data/transcription/service.ts';

const NOW = '2026-11-01T10:00:00.000Z';

class FakeTasks extends TaskRepository {
  tasks = new Map<string, Task>();
  next = 1;
  constructor() {
    super({} as DatabaseClient);
  }
  override async create({ callId, type, metadata }: NewTask): Promise<Task> {
    const task: Task = {
      id: `t${this.next++}`, callId, type, metadata, status: 'QUEUED', error: null,
      startedAt: null, finishedAt: null, createdAt: NOW, updatedAt: NOW,
    };
    this.tasks.set(task.id, task);
    return task;
  }
  override async findById(id: string): Promise<Task | null> {
    return this.tasks.get(id) ?? null;
  }
  override async findUnfinished(callId: string): Promise<Task | null> {
    return [...this.tasks.values()].find((t) => t.callId === callId && ['QUEUED', 'RUNNING'].includes(t.status)) ?? null;
  }
  override async update(id: string, change: TaskChange): Promise<Task | null> {
    const task = this.tasks.get(id);
    if (!task) return null;
    const updated: Task = {
      ...task,
      status: change.status,
      error: change.error,
      startedAt: change.startedAt?.toISOString() ?? task.startedAt,
      finishedAt: change.finishedAt?.toISOString() ?? task.finishedAt,
    };
    this.tasks.set(id, updated);
    return updated;
  }
}

class FakeCalls extends CallService {
  statuses: string[] = [];
  constructor() {
    super({} as never, {} as never, {} as never, {} as never);
  }
  override async get(id: string): Promise<Call> {
    if (id !== 'c1') throw new CallError(404, `Call ${id} not found`);
    return { id } as Call;
  }
  override async updateStatus(id: string, input: UpdateStatusInput): Promise<Status> {
    this.statuses.push(`${id}: ${input.value}${input.error ? ` (${input.error})` : ''}`);
    return { id: 's1', value: input.value, error: input.error ?? null, createdAt: NOW, updatedAt: NOW };
  }
}

class FakeTranscriptions extends TranscriptionService {
  transcriptions: Transcription[] = [];
  deleted: string[] = [];
  constructor() {
    super({} as never, {} as never);
  }
  override async list(callId?: string): Promise<Transcription[]> {
    return this.transcriptions.filter((t) => t.callId === callId);
  }
  override async delete(id: string): Promise<void> {
    this.deleted.push(id);
    this.transcriptions = this.transcriptions.filter((t) => t.id !== id);
  }
}

function setup() {
  const tasks = new FakeTasks();
  const calls = new FakeCalls();
  const transcriptions = new FakeTranscriptions();
  const service = new TaskService(tasks, calls, transcriptions);
  const addTranscription = () =>
    transcriptions.transcriptions.push({ id: 'tr1', callId: 'c1', fileId: 'f1', createdAt: NOW, updatedAt: NOW });
  return { tasks, calls, transcriptions, service, addTranscription };
}

const isTaskError = (status: number) => (err: unknown) => err instanceof TaskError && err.status === status;

describe('TaskService.create', () => {
  it('a transcription replaces the old one: deletes it and sets the call back to UPLOADED', async () => {
    const { calls, transcriptions, service, addTranscription } = setup();
    addTranscription();

    const task = await service.create({ callId: 'c1', type: 'TRANSCRIPTION', metadata: { variantId: 'vad_5s' } });

    assert.equal(task.status, 'QUEUED');
    assert.deepEqual(task.metadata, { variantId: 'vad_5s' });
    assert.deepEqual(transcriptions.deleted, ['tr1']);
    assert.deepEqual(calls.statuses, ['c1: UPLOADED']);
  });

  it('an analysis needs a transcription and sets the call back to TRANSCRIBED', async () => {
    const { calls, service, addTranscription } = setup();
    await assert.rejects(service.create({ callId: 'c1', type: 'ANALYSIS' }), isTaskError(409));

    addTranscription();
    const task = await service.create({ callId: 'c1', type: 'ANALYSIS' });
    assert.deepEqual(task.metadata, {});
    assert.deepEqual(calls.statuses, ['c1: TRANSCRIBED']);
  });

  it('refuses a second unfinished task for the same call', async () => {
    const { service } = setup();
    await service.create({ callId: 'c1', type: 'TRANSCRIPTION' });
    await assert.rejects(service.create({ callId: 'c1', type: 'TRANSCRIPTION' }), isTaskError(409));
  });

  it('rejects invalid input with 400', async () => {
    const { service } = setup();
    const invalid: unknown[] = [
      null,
      { type: 'TRANSCRIPTION' },
      { callId: 'c1', type: 'SUMMARY' },
      { callId: 'c1', type: 'TRANSCRIPTION', metadata: ['a'] },
      { callId: 'c1', type: 'TRANSCRIPTION', metadata: 'a' },
      { callId: 'nope', type: 'TRANSCRIPTION' },
    ];
    for (const input of invalid) {
      await assert.rejects(service.create(input as CreateTaskInput), isTaskError(400), JSON.stringify(input));
    }
  });
});

describe('TaskService.update', () => {
  it('moves a transcription through RUNNING and SUCCEEDED, and the call with it', async () => {
    const { calls, service, addTranscription } = setup();
    const { id } = await service.create({ callId: 'c1', type: 'TRANSCRIPTION' });

    const running = await service.update(id, { status: 'RUNNING' });
    assert.ok(running.startedAt);
    assert.equal(running.finishedAt, null);

    await assert.rejects(service.update(id, { status: 'SUCCEEDED' }), isTaskError(409), 'no transcription saved yet');
    addTranscription();
    const done = await service.update(id, { status: 'SUCCEEDED' });
    assert.ok(done.finishedAt);

    assert.deepEqual(calls.statuses, ['c1: UPLOADED', 'c1: TRANSCRIBING', 'c1: TRANSCRIBED']);
  });

  it('a failure keeps its reason, on the task and on the call', async () => {
    const { calls, service } = setup();
    const { id } = await service.create({ callId: 'c1', type: 'TRANSCRIPTION' });

    const failed = await service.update(id, { status: 'FAILED', error: ' Whisper crashed ' });
    assert.equal(failed.error, 'Whisper crashed');
    assert.equal(calls.statuses.at(-1), 'c1: FAILED (Whisper crashed)');
  });

  it('moves an analysis to ANALYZING and ANALYZED', async () => {
    const { calls, service, addTranscription } = setup();
    addTranscription();
    const { id } = await service.create({ callId: 'c1', type: 'ANALYSIS' });
    await service.update(id, { status: 'RUNNING' });
    await service.update(id, { status: 'SUCCEEDED' });
    assert.deepEqual(calls.statuses, ['c1: TRANSCRIBED', 'c1: ANALYZING', 'c1: ANALYZED']);
  });

  it('allows RUNNING again (a redelivered run), but nothing after the end', async () => {
    const { service } = setup();
    const { id } = await service.create({ callId: 'c1', type: 'TRANSCRIPTION' });

    await assert.rejects(service.update(id, { status: 'SUCCEEDED' }), isTaskError(409), 'QUEUED -> SUCCEEDED');
    await service.update(id, { status: 'RUNNING' });
    await service.update(id, { status: 'RUNNING' });
    await service.update(id, { status: 'FAILED', error: 'Out of memory' });
    await assert.rejects(service.update(id, { status: 'RUNNING' }), isTaskError(409), 'FAILED -> RUNNING');
  });

  it('rejects an invalid status or error with 400, and an unknown task with 404', async () => {
    const { service } = setup();
    const { id } = await service.create({ callId: 'c1', type: 'TRANSCRIPTION' });
    const invalid: unknown[] = [null, { status: 'DONE' }, { status: 'FAILED' }, { status: 'FAILED', error: '  ' }, { status: 'RUNNING', error: 'x' }];
    for (const input of invalid) {
      await assert.rejects(service.update(id, input as UpdateTaskInput), isTaskError(400), JSON.stringify(input));
    }
    await assert.rejects(service.update('nope', { status: 'RUNNING' }), isTaskError(404));
  });

  it('a call can get a new task once the old one has ended', async () => {
    const { service } = setup();
    const first = await service.create({ callId: 'c1', type: 'TRANSCRIPTION' });
    await service.update(first.id, { status: 'FAILED', error: 'Whisper crashed' });
    const second = await service.create({ callId: 'c1', type: 'TRANSCRIPTION' });
    assert.notEqual(second.id, first.id);
  });
});
