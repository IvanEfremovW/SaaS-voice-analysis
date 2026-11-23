import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import type { DatabaseClient } from '#app/infrastructure/database.ts';
import type { S3Storage } from '#app/infrastructure/s3.ts';
import { CallError } from '#app/modules/data/call/entity.ts';
import type { Call, CallMetadata, CreateCallInput } from '#app/modules/data/call/entity.ts';
import { CallRepository } from '#app/modules/data/call/repository.ts';
import { CallService } from '#app/modules/data/call/service.ts';
import type { File, FileContent, UploadFileInput } from '#app/modules/data/file/entity.ts';
import type { FileRepository } from '#app/modules/data/file/repository.ts';
import { FileService } from '#app/modules/data/file/service.ts';
import type { Status, UpdateStatusInput } from '#app/modules/data/status/entity.ts';
import type { StatusRepository } from '#app/modules/data/status/repository.ts';
import { StatusService } from '#app/modules/data/status/service.ts';
import type { Transcription } from '#app/modules/data/transcription/entity.ts';
import type { TranscriptionRepository } from '#app/modules/data/transcription/repository.ts';
import { TranscriptionService } from '#app/modules/data/transcription/service.ts';

const NOW = '2026-11-01T10:00:00.000Z';
const log: string[] = [];

class FakeFiles extends FileService {
  next = 1;
  constructor() {
    super({} as FileRepository, {} as S3Storage, 0);
  }
  override async upload({ name }: UploadFileInput): Promise<File> {
    const id = `file${this.next++}`;
    log.push(`upload ${id} ${name}`);
    return { id, name, type: 'call_recording', contentType: 'audio/wav', sizeBytes: 4, checksum: id, createdAt: NOW, updatedAt: NOW };
  }
  override async download(id: string): Promise<FileContent> {
    return { file: { id } as File, data: Buffer.from('RIFF') };
  }
  override async delete(id: string): Promise<void> {
    log.push(`delete file ${id}`);
  }
}

class FakeStatuses extends StatusService {
  constructor() {
    super({} as StatusRepository);
  }
  override async update(id: string, input: UpdateStatusInput): Promise<Status> {
    log.push(`status ${id} -> ${input.value}`);
    return { id, value: input.value, error: null, createdAt: NOW, updatedAt: NOW };
  }
}

class FakeTranscriptions extends TranscriptionService {
  transcriptions: Transcription[] = [];
  constructor() {
    super({} as TranscriptionRepository, {} as FileService);
  }
  override async list(callId?: string) {
    return this.transcriptions.filter((t) => t.callId === callId);
  }
  override async delete(id: string): Promise<void> {
    log.push(`delete transcription ${id}`);
  }
}

class FakeCalls extends CallRepository {
  calls = new Map<string, Call>();
  failCreate: Error | null = null;
  constructor() {
    super({} as DatabaseClient);
  }
  override async create(metadata: CallMetadata, fileId: string): Promise<Call> {
    if (this.failCreate) throw this.failCreate;
    const status: Status = { id: 's1', value: 'UPLOADED', error: null, createdAt: NOW, updatedAt: NOW };
    const call: Call = { id: 'c1', ...metadata, fileId, status, createdAt: NOW, updatedAt: NOW };
    this.calls.set(call.id, call);
    log.push(`create call with ${fileId}`);
    return call;
  }
  override async findById(id: string) {
    return this.calls.get(id) ?? null;
  }
  override async update(id: string, metadata: Partial<CallMetadata>, fileId?: string) {
    const call = this.calls.get(id);
    if (!call) return null;
    const updated = { ...call, ...metadata, ...(fileId && { fileId }) };
    this.calls.set(id, updated);
    if (fileId) log.push(`call points to ${fileId}`);
    return updated;
  }
  override async delete(id: string) {
    log.push(`delete call ${id}`);
    return this.calls.delete(id);
  }
}

function setup() {
  log.length = 0;
  const calls = new FakeCalls();
  const transcriptions = new FakeTranscriptions();
  const service = new CallService(calls, new FakeFiles(), new FakeStatuses(), transcriptions);
  return { calls, transcriptions, service };
}

const input: CreateCallInput = {
  userId: 'u1',
  clientPhone: ' +7 900 123-45-67 ',
  direction: 'INCOMING',
  startedAt: '2026-11-01T09:00:00+03:00',
  durationSec: 95,
  recording: { name: 'call.wav', data: Buffer.from('RIFF') },
};

const isCallError = (status: number) => (err: unknown) => err instanceof CallError && err.status === status;

describe('CallService', () => {
  it('uploads the recording, then creates the call', async () => {
    const { service } = setup();
    const call = await service.create(input);
    assert.equal(call.fileId, 'file1');
    assert.equal(call.clientPhone, '+7 900 123-45-67');
    assert.equal(call.status.value, 'UPLOADED');
    assert.deepEqual(log, ['upload file1 call.wav', 'create call with file1']);
  });

  it('rejects invalid metadata before uploading anything', async () => {
    const { service } = setup();
    const invalid: Partial<CreateCallInput>[] = [
      { userId: '' },
      { clientPhone: 'call me' },
      { direction: 'SIDEWAYS' as never },
      { startedAt: 'yesterday' },
      { durationSec: -1 },
      { durationSec: 1.5 },
    ];
    for (const change of invalid) {
      await assert.rejects(service.create({ ...input, ...change }), isCallError(400), JSON.stringify(change));
    }
    assert.deepEqual(log, []);
  });

  it('removes the uploaded recording when the call cannot be created', async () => {
    const { calls, service } = setup();
    calls.failCreate = new CallError(400, 'User u1 does not exist');
    await assert.rejects(service.create(input), isCallError(400));
    assert.deepEqual(log, ['upload file1 call.wav', 'delete file file1']);
  });

  it('replaces the recording: new file, transcription removed, status reset, old file deleted', async () => {
    const { transcriptions, service } = setup();
    await service.create(input);
    transcriptions.transcriptions = [{ id: 't1', callId: 'c1', fileId: 'tf', createdAt: NOW, updatedAt: NOW }];
    log.length = 0;

    const call = await service.replaceRecording('c1', { name: 'better.wav', data: Buffer.from('RIFF') });

    assert.equal(call.fileId, 'file2');
    assert.deepEqual(log, [
      'upload file2 better.wav',
      'call points to file2',
      'delete transcription t1',
      'status s1 -> UPLOADED',
      'delete file file1',
    ]);
  });

  it('deletes the transcription, then the call, then its recording', async () => {
    const { transcriptions, service } = setup();
    await service.create(input);
    transcriptions.transcriptions = [{ id: 't1', callId: 'c1', fileId: 'tf', createdAt: NOW, updatedAt: NOW }];
    log.length = 0;

    await service.delete('c1');

    assert.deepEqual(log, ['delete transcription t1', 'delete call c1', 'delete file file1']);
  });

  it('updates the status of the call', async () => {
    const { service } = setup();
    await service.create(input);
    const status = await service.updateStatus('c1', { value: 'TRANSCRIBING' });
    assert.equal(status.id, 's1');
    assert.equal(status.value, 'TRANSCRIBING');
  });

  it('validates list filters and answers 404 for an unknown call', async () => {
    const { service } = setup();
    await assert.rejects(service.list({ status: 'DONE' as never }), isCallError(400));
    await assert.rejects(service.list({ from: 'yesterday' }), isCallError(400));
    await assert.rejects(service.get('nope'), isCallError(404));
    await assert.rejects(service.delete('nope'), isCallError(404));
    await assert.rejects(service.replaceRecording('nope', input.recording), isCallError(404));
  });
});
