import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { describe, it } from 'node:test';
import type { DatabaseClient } from '#app/infrastructure/database.ts';
import type { S3Storage } from '#app/infrastructure/s3.ts';
import { FileError } from '#app/modules/data/file/entity.ts';
import type { File, FileContent, FileType } from '#app/modules/data/file/entity.ts';
import type { FileRepository } from '#app/modules/data/file/repository.ts';
import { FileService } from '#app/modules/data/file/service.ts';
import { TranscriptionError } from '#app/modules/data/transcription/entity.ts';
import type { CreateTranscriptionInput, Transcription } from '#app/modules/data/transcription/entity.ts';
import { TranscriptionRepository } from '#app/modules/data/transcription/repository.ts';
import { TranscriptionService } from '#app/modules/data/transcription/service.ts';

const file = (id: string, type: FileType): File => ({
  id,
  name: `${id}.json`,
  type,
  contentType: 'application/json',
  sizeBytes: 2,
  checksum: id,
  createdAt: '2026-11-01T10:00:00.000Z',
  updatedAt: '2026-11-01T10:00:00.000Z',
});

class FakeFileService extends FileService {
  files = new Map<string, File>([
    ['t1', file('t1', 'transcription')],
    ['t2', file('t2', 'transcription')],
    ['rec', file('rec', 'call_recording')],
  ]);

  constructor() {
    super({} as FileRepository, {} as S3Storage, 0);
  }

  override async get(id: string): Promise<File> {
    const found = this.files.get(id);
    if (!found) throw new FileError(404, `File ${id} not found`);
    return found;
  }

  override async download(id: string): Promise<FileContent> {
    return { file: await this.get(id), data: Buffer.from('{"text":"hello"}') };
  }

  override async delete(id: string): Promise<void> {
    this.files.delete(id);
  }
}

class FakeTranscriptionRepository extends TranscriptionRepository {
  rows = new Map<string, Transcription>();

  constructor() {
    super({} as DatabaseClient);
  }

  override async create({ callId, fileId }: CreateTranscriptionInput): Promise<Transcription> {
    const now = new Date().toISOString();
    const row = { id: randomUUID(), callId, fileId, createdAt: now, updatedAt: now };
    this.rows.set(row.id, row);
    return row;
  }

  override async findById(id: string) {
    return this.rows.get(id) ?? null;
  }

  override async findByCallId(callId: string) {
    return [...this.rows.values()].find((t) => t.callId === callId) ?? null;
  }

  override async findByFileId(fileId: string) {
    return [...this.rows.values()].find((t) => t.fileId === fileId) ?? null;
  }

  override async list() {
    return [...this.rows.values()];
  }

  override async delete(id: string) {
    return this.rows.delete(id);
  }
}

function setup() {
  const files = new FakeFileService();
  const repo = new FakeTranscriptionRepository();
  return { files, repo, service: new TranscriptionService(repo, files) };
}

const isError = (status: number) => (err: unknown) => err instanceof TranscriptionError && err.status === status;

describe('TranscriptionService', () => {
  it('links a transcription file to a call', async () => {
    const { service } = setup();
    const transcription = await service.create({ callId: 'c1', fileId: 't1' });
    assert.equal(transcription.callId, 'c1');
    assert.equal(transcription.fileId, 't1');
    assert.deepEqual(await service.list('c1'), [transcription]);
    assert.deepEqual(await service.list('other'), []);
  });

  it('rejects a missing file, a non-transcription file and bad input with 400', async () => {
    const { service } = setup();
    await assert.rejects(service.create({ callId: 'c1', fileId: 'nope' }), isError(400));
    await assert.rejects(service.create({ callId: 'c1', fileId: 'rec' }), isError(400));
    await assert.rejects(service.create({ callId: '', fileId: 't1' }), isError(400));
    await assert.rejects(service.create(null as unknown as CreateTranscriptionInput), isError(400));
  });

  it('allows one transcription per call and per file (409)', async () => {
    const { service } = setup();
    await service.create({ callId: 'c1', fileId: 't1' });
    await assert.rejects(service.create({ callId: 'c1', fileId: 't2' }), isError(409));
    await assert.rejects(service.create({ callId: 'c2', fileId: 't1' }), isError(409));
  });

  it('returns the content of the transcription file', async () => {
    const { service } = setup();
    const { id } = await service.create({ callId: 'c1', fileId: 't1' });
    const content = await service.content(id);
    assert.equal(content.file.id, 't1');
    assert.equal(content.data.toString(), '{"text":"hello"}');
  });

  it('deletes the transcription together with its file', async () => {
    const { files, repo, service } = setup();
    const { id } = await service.create({ callId: 'c1', fileId: 't1' });
    await service.delete(id);
    assert.equal(repo.rows.size, 0);
    assert.equal(files.files.has('t1'), false);
  });

  it('answers 404 for an unknown transcription', async () => {
    const { service } = setup();
    await assert.rejects(service.get('nope'), isError(404));
    await assert.rejects(service.getByCallId('nope'), isError(404));
    await assert.rejects(service.delete('nope'), isError(404));
  });
});
