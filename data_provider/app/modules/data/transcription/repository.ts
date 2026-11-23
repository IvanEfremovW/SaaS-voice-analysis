import type { DatabaseClient } from '#app/infrastructure/database.ts';
import type { Transcription as TranscriptionRow } from '#app/generated/prisma/client.ts';
import { TranscriptionError } from './entity.ts';
import type { CreateTranscriptionInput, Transcription } from './entity.ts';

export class TranscriptionRepository {
  #db: DatabaseClient;

  constructor(db: DatabaseClient) {
    this.#db = db;
  }

  async create({ callId, fileId }: CreateTranscriptionInput): Promise<Transcription> {
    try {
      return toTranscription(await this.#db.transcription.create({ data: { call_id: callId, file_id: fileId } }));
    } catch (err) {
      switch (errorCode(err)) {
        case 'P2002':
          throw new TranscriptionError(409, 'The call or the file already has a transcription');
        case 'P2003':
          throw new TranscriptionError(400, `Call ${callId} does not exist`);
        default:
          throw err;
      }
    }
  }

  async findById(id: string): Promise<Transcription | null> {
    const row = await this.#db.transcription.findUnique({ where: { id } });
    return row && toTranscription(row);
  }

  async findByCallId(callId: string): Promise<Transcription | null> {
    const row = await this.#db.transcription.findUnique({ where: { call_id: callId } });
    return row && toTranscription(row);
  }

  async findByFileId(fileId: string): Promise<Transcription | null> {
    const row = await this.#db.transcription.findUnique({ where: { file_id: fileId } });
    return row && toTranscription(row);
  }

  async list(): Promise<Transcription[]> {
    const rows = await this.#db.transcription.findMany({ orderBy: { created_at: 'asc' } });
    return rows.map(toTranscription);
  }

  /** False if there is no such transcription. */
  async delete(id: string): Promise<boolean> {
    try {
      await this.#db.transcription.delete({ where: { id } });
      return true;
    } catch (err) {
      if (errorCode(err) === 'P2025') return false;
      throw err;
    }
  }
}

function toTranscription(row: TranscriptionRow): Transcription {
  return {
    id: row.id,
    callId: row.call_id,
    fileId: row.file_id,
    createdAt: row.created_at.toISOString(),
    updatedAt: row.updated_at.toISOString(),
  };
}

// https://www.prisma.io/docs/orm/reference/error-reference
function errorCode(err: unknown): string | undefined {
  return (err as { code?: string }).code;
}
