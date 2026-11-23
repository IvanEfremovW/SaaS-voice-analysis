import type { DatabaseClient } from '#app/infrastructure/database.ts';
import type { File as FileRow } from '#app/generated/prisma/client.ts';
import { FileError } from './entity.ts';
import type { FileType } from './entity.ts';
import type { StoredFile } from './types.ts';

export type NewFile = Omit<StoredFile, 'createdAt' | 'updatedAt'>;

export class FileRepository {
  #db: DatabaseClient;

  constructor(db: DatabaseClient) {
    this.#db = db;
  }

  async create(file: NewFile): Promise<StoredFile> {
    try {
      const row = await this.#db.file.create({
        data: {
          id: file.id,
          uri: file.uri,
          name: file.name,
          type: file.type,
          content_type: file.contentType,
          size_bytes: BigInt(file.sizeBytes),
          checksum: file.checksum,
        },
      });
      return toStoredFile(row);
    } catch (err) {
      throw translate(err);
    }
  }

  async findById(id: string): Promise<StoredFile | null> {
    const row = await this.#db.file.findUnique({ where: { id } });
    return row && toStoredFile(row);
  }

  async findByChecksum(checksum: string): Promise<StoredFile | null> {
    const row = await this.#db.file.findUnique({ where: { checksum } });
    return row && toStoredFile(row);
  }

  async list(type?: FileType): Promise<StoredFile[]> {
    const rows = await this.#db.file.findMany({ where: type ? { type } : {}, orderBy: { created_at: 'asc' } });
    return rows.map(toStoredFile);
  }

  /** False if there is no such file. */
  async delete(id: string): Promise<boolean> {
    try {
      await this.#db.file.delete({ where: { id } });
      return true;
    } catch (err) {
      if (errorCode(err) === 'P2025') return false;
      throw translate(err);
    }
  }
}

function toStoredFile(row: FileRow): StoredFile {
  return {
    id: row.id,
    uri: row.uri,
    name: row.name,
    type: row.type as FileType,
    contentType: row.content_type,
    sizeBytes: Number(row.size_bytes),
    checksum: row.checksum,
    createdAt: row.created_at.toISOString(),
    updatedAt: row.updated_at.toISOString(),
  };
}

// https://www.prisma.io/docs/orm/reference/error-reference
function errorCode(err: unknown): string | undefined {
  return (err as { code?: string }).code;
}

function translate(err: unknown): unknown {
  switch (errorCode(err)) {
    case 'P2002':
      return new FileError(409, 'The same file is already stored');
    case 'P2003':
      return new FileError(409, 'The file is used by a call or a transcription');
    default:
      return err;
  }
}
