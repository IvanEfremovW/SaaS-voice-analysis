import { database } from '#app/infrastructure/database.ts';
import type { FileContent } from '#app/modules/data/file/entity.ts';
import { fileService } from '#app/modules/data/file/service.ts';
import type { FileService } from '#app/modules/data/file/service.ts';
import { CALL_STATUSES } from '#app/modules/data/status/entity.ts';
import type { Status, UpdateStatusInput } from '#app/modules/data/status/entity.ts';
import { statusService } from '#app/modules/data/status/service.ts';
import type { StatusService } from '#app/modules/data/status/service.ts';
import { transcriptionService } from '#app/modules/data/transcription/service.ts';
import type { TranscriptionService } from '#app/modules/data/transcription/service.ts';
import { CALL_DIRECTIONS, CallError } from './entity.ts';
import type { Call, CallFilter, CallMetadata, CreateCallInput, Recording, UpdateCallInput } from './entity.ts';
import { CallRepository } from './repository.ts';

export class CallService {
  #calls: CallRepository;
  #files: FileService;
  #statuses: StatusService;
  #transcriptions: TranscriptionService;

  constructor(calls: CallRepository, files: FileService, statuses: StatusService, transcriptions: TranscriptionService) {
    this.#calls = calls;
    this.#files = files;
    this.#statuses = statuses;
    this.#transcriptions = transcriptions;
  }

  /** Uploads the recording (with the file module's validation), then saves the call with status UPLOADED. */
  async create({ recording, ...metadata }: CreateCallInput): Promise<Call> {
    const checked = validate(metadata, true) as CallMetadata;
    const file = await this.#uploadRecording(recording);
    try {
      return await this.#calls.create(checked, file.id);
    } catch (err) {
      await this.#files.delete(file.id).catch(() => {});
      throw err;
    }
  }

  async get(id: string): Promise<Call> {
    return (await this.#calls.findById(id)) ?? notFound(id);
  }

  async list(filter: CallFilter = {}): Promise<Call[]> {
    if (filter.status !== undefined && !CALL_STATUSES.includes(filter.status)) {
      throw new CallError(400, `"status" must be one of ${CALL_STATUSES.join(', ')}`);
    }
    for (const key of ['from', 'to'] as const) {
      if (filter[key] !== undefined && Number.isNaN(Date.parse(filter[key]))) {
        throw new CallError(400, `"${key}" must be an ISO-8601 date`);
      }
    }
    return this.#calls.list(filter);
  }

  async update(id: string, input: UpdateCallInput): Promise<Call> {
    return (await this.#calls.update(id, validate(input, false))) ?? notFound(id);
  }

  async downloadRecording(id: string): Promise<FileContent> {
    return this.#files.download((await this.get(id)).fileId);
  }

  /**
   * Replaces the recording. Its transcription no longer matches the audio, so it is deleted
   * and processing starts again from UPLOADED.
   */
  async replaceRecording(id: string, recording: Recording): Promise<Call> {
    const call = await this.get(id);
    const file = await this.#uploadRecording(recording);
    try {
      await this.#calls.update(id, {}, file.id);
    } catch (err) {
      await this.#files.delete(file.id).catch(() => {});
      throw err;
    }
    await this.#deleteTranscription(id);
    await this.#statuses.update(call.status.id, { value: 'UPLOADED' });
    await this.#files.delete(call.fileId).catch((err) => console.error(`Old recording ${call.fileId} was not removed:`, err));
    return this.get(id);
  }

  async updateStatus(id: string, input: UpdateStatusInput): Promise<Status> {
    return this.#statuses.update((await this.get(id)).status.id, input);
  }

  /** Deletes the call with everything that belongs to it: transcription, status and recording. */
  async delete(id: string): Promise<void> {
    const call = await this.get(id);
    await this.#deleteTranscription(id);
    if (!(await this.#calls.delete(id))) notFound(id);
    await this.#files.delete(call.fileId).catch((err) => console.error(`Recording ${call.fileId} was not removed:`, err));
  }

  #uploadRecording({ name, data }: Recording) {
    return this.#files.upload({ name: name || 'recording', type: 'call_recording', data });
  }

  async #deleteTranscription(callId: string): Promise<void> {
    for (const transcription of await this.#transcriptions.list(callId)) {
      await this.#transcriptions.delete(transcription.id);
    }
  }
}

/** Checks metadata at runtime (it comes from a request) and returns only the known fields. */
function validate(input: UpdateCallInput, isCreate: boolean): UpdateCallInput {
  if (typeof input !== 'object' || input === null) throw new CallError(400, 'Body must be a JSON object');
  const result: UpdateCallInput = {};
  const required = (key: keyof CallMetadata) => input[key] !== undefined || isCreate;

  if (required('userId')) {
    if (typeof input.userId !== 'string' || !input.userId) throw new CallError(400, '"userId" must be a non-empty string');
    result.userId = input.userId;
  }
  if (required('clientPhone')) {
    if (typeof input.clientPhone !== 'string' || !/^\+?[\d\s()-]{3,32}$/.test(input.clientPhone.trim())) {
      throw new CallError(400, '"clientPhone" must be a phone number');
    }
    result.clientPhone = input.clientPhone.trim();
  }
  if (required('direction')) {
    if (!CALL_DIRECTIONS.includes(input.direction as never)) {
      throw new CallError(400, `"direction" must be one of ${CALL_DIRECTIONS.join(', ')}`);
    }
    result.direction = input.direction as CallMetadata['direction'];
  }
  if (required('startedAt')) {
    if (typeof input.startedAt !== 'string' || Number.isNaN(Date.parse(input.startedAt))) {
      throw new CallError(400, '"startedAt" must be an ISO-8601 date');
    }
    result.startedAt = input.startedAt;
  }
  if (required('durationSec')) {
    if (!Number.isInteger(input.durationSec) || (input.durationSec as number) < 0) {
      throw new CallError(400, '"durationSec" must be a whole number of seconds');
    }
    result.durationSec = input.durationSec as number;
  }
  return result;
}

function notFound(id: string): never {
  throw new CallError(404, `Call ${id} not found`);
}

export const callService = new CallService(new CallRepository(database), fileService, statusService, transcriptionService);
