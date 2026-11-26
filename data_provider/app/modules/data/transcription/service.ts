import { database } from '#app/infrastructure/database.ts';
import { FileError } from '#app/modules/data/file/entity.ts';
import type { FileContent } from '#app/modules/data/file/entity.ts';
import { fileService } from '#app/modules/data/file/service.ts';
import type { FileService } from '#app/modules/data/file/service.ts';
import { TranscriptionError } from './entity.ts';
import type { CreateTranscriptionInput, Transcription } from './entity.ts';
import { TranscriptionRepository } from './repository.ts';

export class TranscriptionService {
  #transcriptions: TranscriptionRepository;
  #files: FileService;

  constructor(transcriptions: TranscriptionRepository, files: FileService) {
    this.#transcriptions = transcriptions;
    this.#files = files;
  }

  /** Links an uploaded "transcription" file to a call; a call has at most one transcription. */
  async create(input: CreateTranscriptionInput): Promise<Transcription> {
    if (typeof input !== 'object' || input === null) throw new TranscriptionError(400, 'Body must be a JSON object');
    const { callId, fileId } = input;
    if (typeof callId !== 'string' || !callId) throw new TranscriptionError(400, '"callId" must be a non-empty string');
    if (typeof fileId !== 'string' || !fileId) throw new TranscriptionError(400, '"fileId" must be a non-empty string');

    const file = await this.#files.get(fileId).catch((err) => {
      throw err instanceof FileError && err.status === 404 ? new TranscriptionError(400, `File ${fileId} does not exist`) : err;
    });
    if (file.type !== 'transcription') {
      throw new TranscriptionError(400, `File ${fileId} is a ${file.type} file, not a transcription`);
    }

    const ofCall = await this.#transcriptions.findByCallId(callId);
    if (ofCall) throw new TranscriptionError(409, `Call ${callId} already has transcription ${ofCall.id}`);
    const ofFile = await this.#transcriptions.findByFileId(fileId);
    if (ofFile) throw new TranscriptionError(409, `File ${fileId} already belongs to transcription ${ofFile.id}`);

    return this.#transcriptions.create({ callId, fileId });
  }

  async get(id: string): Promise<Transcription> {
    return (await this.#transcriptions.findById(id)) ?? notFound(`Transcription ${id}`);
  }

  async getByCallId(callId: string): Promise<Transcription> {
    return (await this.#transcriptions.findByCallId(callId)) ?? notFound(`Transcription of call ${callId}`);
  }

  /** All transcriptions, or only the one of the given call (an empty list if it has none). */
  async list(callId?: string): Promise<Transcription[]> {
    if (callId === undefined) return this.#transcriptions.list();
    const transcription = await this.#transcriptions.findByCallId(callId);
    return transcription ? [transcription] : [];
  }

  /** The transcription's file with its content (JSON). */
  async content(id: string): Promise<FileContent> {
    return this.#files.download((await this.get(id)).fileId);
  }

  /** Deletes the transcription and its file, which nothing else uses. */
  async delete(id: string): Promise<void> {
    const transcription = await this.get(id);
    if (!(await this.#transcriptions.delete(id))) notFound(`Transcription ${id}`);
    await this.#files.delete(transcription.fileId).catch((err) => {
      console.error(`File ${transcription.fileId} of deleted transcription ${id} was not removed:`, err);
    });
  }
}

function notFound(what: string): never {
  throw new TranscriptionError(404, `${what} not found`);
}

export const transcriptionService = new TranscriptionService(new TranscriptionRepository(database), fileService);
