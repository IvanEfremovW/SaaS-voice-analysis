import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { describe, it } from 'node:test';
import type { S3Client } from '@aws-sdk/client-s3';
import type { DatabaseClient } from '#app/infrastructure/database.ts';
import { S3Storage } from '#app/infrastructure/s3.ts';
import { FileError } from '#app/modules/data/file/entity.ts';
import type { FileType } from '#app/modules/data/file/entity.ts';
import { FileRepository } from '#app/modules/data/file/repository.ts';
import type { NewFile } from '#app/modules/data/file/repository.ts';
import { FileService } from '#app/modules/data/file/service.ts';
import type { StoredFile } from '#app/modules/data/file/types.ts';

const WAV = Buffer.concat([Buffer.from('RIFF'), Buffer.alloc(4), Buffer.from('WAVEfmt '), Buffer.alloc(16)]);

class FakeRepository extends FileRepository {
  files = new Map<string, StoredFile>();
  failCreate = false;
  deleteError: Error | null = null;

  constructor() {
    super({} as DatabaseClient);
  }

  override async create(file: NewFile): Promise<StoredFile> {
    if (this.failCreate) throw new Error('database is down');
    const now = new Date().toISOString();
    const stored = { ...file, createdAt: now, updatedAt: now };
    this.files.set(file.id, stored);
    return stored;
  }

  override async findById(id: string) {
    return this.files.get(id) ?? null;
  }

  override async findByChecksum(checksum: string) {
    return [...this.files.values()].find((f) => f.checksum === checksum) ?? null;
  }

  override async list(type?: FileType) {
    return [...this.files.values()].filter((f) => !type || f.type === type);
  }

  override async delete(id: string) {
    if (this.deleteError) throw this.deleteError;
    return this.files.delete(id);
  }
}

class FakeStorage extends S3Storage {
  objects = new Map<string, Buffer>();

  constructor() {
    super({} as S3Client, 'bucket');
  }

  override async upload(key: string, body: Buffer): Promise<string> {
    const uri = `s3://bucket/${key}`;
    this.objects.set(uri, body);
    return uri;
  }

  override async download(uri: string): Promise<Buffer> {
    const data = this.objects.get(uri);
    if (!data) throw new Error(`no object ${uri}`);
    return data;
  }

  override async delete(uri: string): Promise<void> {
    this.objects.delete(uri);
  }
}

function setup(maxSizeBytes = 1024) {
  const repo = new FakeRepository();
  const storage = new FakeStorage();
  return { repo, storage, service: new FileService(repo, storage, maxSizeBytes) };
}

const isFileError = (status: number) => (err: unknown) => err instanceof FileError && err.status === status;

describe('FileService.upload', () => {
  it('stores the file in S3 and its metadata in the database', async () => {
    const { repo, storage, service } = setup();

    const file = await service.upload({ name: ' call.wav ', type: 'call_recording', data: WAV });

    assert.equal(file.name, 'call.wav');
    assert.equal(file.contentType, 'audio/wav');
    assert.equal(file.sizeBytes, WAV.length);
    assert.equal(file.checksum, createHash('sha256').update(WAV).digest('hex'));
    assert.equal('uri' in file, false);

    const uri = repo.files.get(file.id)?.uri ?? '';
    assert.match(uri, new RegExp(`^s3://bucket/call_recording/\\d{4}/\\d{2}/${file.id}\\.wav$`));
    assert.deepEqual(storage.objects.get(uri), WAV);
  });

  it('rejects an empty, too large, unknown or mislabelled file', async () => {
    const { service } = setup(WAV.length - 1);
    await assert.rejects(service.upload({ name: 'a.wav', type: 'call_recording', data: Buffer.alloc(0) }), isFileError(400));
    await assert.rejects(service.upload({ name: 'a.wav', type: 'call_recording', data: WAV }), isFileError(413));
    await assert.rejects(service.upload({ name: 'a.wav', type: 'video' as FileType, data: WAV }), isFileError(400));
    await assert.rejects(service.upload({ name: '  ', type: 'call_recording', data: WAV }), isFileError(400));

    const { service: roomy } = setup();
    await assert.rejects(roomy.upload({ name: 'a.wav', type: 'call_recording', data: Buffer.from('not audio') }), isFileError(400));
  });

  it('refuses a duplicate and does not upload it again', async () => {
    const { storage, service } = setup();
    const first = await service.upload({ name: 'a.wav', type: 'call_recording', data: WAV });

    await assert.rejects(
      service.upload({ name: 'renamed.wav', type: 'call_recording', data: WAV }),
      (err) => isFileError(409)(err) && (err as Error).message.includes(first.id),
    );
    assert.equal(storage.objects.size, 1);
  });

  it('removes the uploaded object when saving the metadata fails', async () => {
    const { repo, storage, service } = setup();
    repo.failCreate = true;
    await assert.rejects(service.upload({ name: 'a.wav', type: 'call_recording', data: WAV }), /database is down/);
    assert.equal(storage.objects.size, 0);
  });
});

describe('FileService reading and deleting', () => {
  it('downloads the content of a file', async () => {
    const { service } = setup();
    const file = await service.upload({ name: 'a.wav', type: 'call_recording', data: WAV });
    const content = await service.download(file.id);
    assert.deepEqual(content.data, WAV);
    assert.equal(content.file.id, file.id);
  });

  it('deletes the metadata and the stored object', async () => {
    const { repo, storage, service } = setup();
    const file = await service.upload({ name: 'a.wav', type: 'call_recording', data: WAV });
    await service.delete(file.id);
    assert.equal(repo.files.size, 0);
    assert.equal(storage.objects.size, 0);
  });

  it('keeps the object when the file is still in use', async () => {
    const { repo, storage, service } = setup();
    const file = await service.upload({ name: 'a.wav', type: 'call_recording', data: WAV });
    repo.deleteError = new FileError(409, 'The file is used by a call or a transcription');

    await assert.rejects(service.delete(file.id), isFileError(409));
    assert.equal(storage.objects.size, 1);
  });

  it('answers 404 for an unknown file', async () => {
    const { service } = setup();
    await assert.rejects(service.get('nope'), isFileError(404));
    await assert.rejects(service.download('nope'), isFileError(404));
    await assert.rejects(service.delete('nope'), isFileError(404));
  });

  it('lists files, optionally by type', async () => {
    const { service } = setup();
    await service.upload({ name: 'a.wav', type: 'call_recording', data: WAV });
    await service.upload({ name: 't.json', type: 'transcription', data: Buffer.from('{"text":"hi"}') });

    assert.equal((await service.list()).length, 2);
    assert.deepEqual((await service.list('transcription')).map((f) => f.name), ['t.json']);
    await assert.rejects(service.list('video' as FileType), isFileError(400));
  });
});
