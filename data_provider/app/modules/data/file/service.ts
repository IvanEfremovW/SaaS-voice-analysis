import { createHash, randomUUID } from 'node:crypto';
import { config } from '#app/config.ts';
import { database } from '#app/infrastructure/database.ts';
import { s3Storage } from '#app/infrastructure/s3.ts';
import type { S3Storage } from '#app/infrastructure/s3.ts';
import { FILE_TYPES, FileError } from './entity.ts';
import type { File, FileContent, FileType, UploadFileInput } from './entity.ts';
import { FileRepository } from './repository.ts';
import type { StoredFile } from './types.ts';
import { detectFormat } from './validation.ts';

export class FileService {
  #files: FileRepository;
  #storage: S3Storage;
  #maxSizeBytes: number;

  constructor(files: FileRepository, storage: S3Storage, maxSizeBytes: number) {
    this.#files = files;
    this.#storage = storage;
    this.#maxSizeBytes = maxSizeBytes;
  }

  /** Validates the file, stores it in S3 and its metadata in the database. */
  async upload({ name, type, data }: UploadFileInput): Promise<File> {
    if (typeof name !== 'string' || !name.trim()) throw new FileError(400, '"name" must be a non-empty string');
    if (!FILE_TYPES.includes(type)) throw new FileError(400, `"type" must be one of ${FILE_TYPES.join(', ')}`);
    if (data.length === 0) throw new FileError(400, 'The file is empty');
    if (data.length > this.#maxSizeBytes) throw new FileError(413, `The file is larger than ${this.#maxSizeBytes} bytes`);

    const format = detectFormat(type, data);
    if (!format) throw new FileError(400, `Unsupported format for a ${type} file`);

    const checksum = createHash('sha256').update(data).digest('hex');
    const duplicate = await this.#files.findByChecksum(checksum);
    if (duplicate) throw new FileError(409, `The same file is already stored as ${duplicate.id}`);

    const id = randomUUID();
    const month = new Date().toISOString().slice(0, 7).replace('-', '/');
    const uri = await this.#storage.upload(`${type}/${month}/${id}.${format.extension}`, data, format.contentType);
    try {
      const stored = await this.#files.create({
        id,
        uri,
        name: name.trim(),
        type,
        contentType: format.contentType,
        sizeBytes: data.length,
        checksum,
      });
      return toFile(stored);
    } catch (err) {
      await this.#storage.delete(uri).catch(() => {});
      throw err;
    }
  }

  async get(id: string): Promise<File> {
    return toFile(await this.#find(id));
  }

  async list(type?: FileType): Promise<File[]> {
    if (type !== undefined && !FILE_TYPES.includes(type)) {
      throw new FileError(400, `"type" must be one of ${FILE_TYPES.join(', ')}`);
    }
    return (await this.#files.list(type)).map(toFile);
  }

  async download(id: string): Promise<FileContent> {
    const stored = await this.#find(id);
    return { file: toFile(stored), data: await this.#storage.download(stored.uri) };
  }

  /** Deletes the metadata first: if the file is still used, nothing is removed from S3. */
  async delete(id: string): Promise<void> {
    const stored = await this.#find(id);
    if (!(await this.#files.delete(id))) throw notFound(id);
    await this.#storage.delete(stored.uri).catch((err) => console.error(`File ${id} left in storage:`, err));
  }

  async #find(id: string): Promise<StoredFile> {
    const stored = await this.#files.findById(id);
    if (!stored) throw notFound(id);
    return stored;
  }
}

function toFile({ uri: _uri, ...file }: StoredFile): File {
  return file;
}

function notFound(id: string): FileError {
  return new FileError(404, `File ${id} not found`);
}

export const fileService = new FileService(new FileRepository(database), s3Storage, config.maxFileSizeBytes);
