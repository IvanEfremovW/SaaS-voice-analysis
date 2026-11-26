import { dataProvider } from '#backend/infrastructure/data-provider.ts';
import { HttpError } from '#backend/infrastructure/http.ts';
import { userService } from '#backend/modules/user/service.ts';
import type { UserService } from '#backend/modules/user/service.ts';
import { CallClient } from './client.ts';
import type { Call, CallDetails, CallDirection, CallQuery, CallSort, CallStatus, FileInfo } from './entity.ts';
import type { ProviderCall, ProviderFile } from './types.ts';

const SORTS: CallSort[] = ['startedAt', 'userName', 'clientPhone', 'direction', 'durationSec', 'status'];
const DIRECTIONS: CallDirection[] = ['INCOMING', 'OUTGOING'];
// A worker is busy with the call at these stages.
const IN_PROGRESS: CallStatus[] = ['TRANSCRIBING', 'ANALYZING'];

export class CallService {
  #calls: CallClient;
  #users: UserService;

  constructor(calls: CallClient, users: UserService) {
    this.#calls = calls;
    this.#users = users;
  }

  /** Calls with the names of their employees, filtered and sorted (newest first if no sort is given). */
  async list({ userId, direction, from, to, sort = 'startedAt', order = 'desc' }: CallQuery = {}): Promise<Call[]> {
    if (direction !== undefined && !DIRECTIONS.includes(direction)) {
      throw new HttpError(400, `"direction" must be one of ${DIRECTIONS.join(', ')}`);
    }
    if (!SORTS.includes(sort)) throw new HttpError(400, `"sort" must be one of ${SORTS.join(', ')}`);
    if (order !== 'asc' && order !== 'desc') throw new HttpError(400, '"order" must be asc or desc');

    const [calls, users] = await Promise.all([this.#calls.list({ userId, from, to }), this.#users.list()]);
    const names = new Map(users.map((user) => [user.id, user.name]));
    return calls
      .filter((call) => direction === undefined || call.direction === direction)
      .map((call) => toCall(call, names.get(call.userId) ?? '—'))
      .sort((a, b) => compare(a[sort], b[sort]) * (order === 'asc' ? 1 : -1));
  }

  /** The call with its employee, recording and transcription. */
  async get(id: string): Promise<CallDetails> {
    const call = await this.#calls.get(id);
    const [user, recording, transcription] = await Promise.all([
      this.#users.get(call.userId),
      this.#calls.getFile(call.fileId),
      this.#calls.findTranscription(id),
    ]);
    const transcriptionFile = transcription && (await this.#calls.getFile(transcription.fileId));
    return {
      ...toCall(call, user.name),
      recording: toFileInfo(recording),
      transcription:
        transcription && transcriptionFile && { createdAt: transcription.createdAt, file: toFileInfo(transcriptionFile) },
    };
  }

  async downloadRecording(id: string): Promise<Response> {
    return this.#calls.downloadFile((await this.#calls.get(id)).fileId);
  }

  async downloadTranscription(id: string): Promise<Response> {
    const transcription = await this.#calls.findTranscription(id);
    if (!transcription) throw new HttpError(404, `Call ${id} has no transcription`);
    return this.#calls.downloadFile(transcription.fileId);
  }

  /**
   * Deletes the old transcription (a call keeps at most one) and puts the call back to UPLOADED,
   * the stage of waiting for a transcription. There is no transcription worker yet: once there is
   * a queue for it, the call will also be sent to the queue here.
   */
  async requestTranscription(id: string): Promise<void> {
    const call = await this.#calls.get(id);
    if (IN_PROGRESS.includes(call.status.value)) throw new HttpError(409, `Call ${id} is being processed right now`);
    const transcription = await this.#calls.findTranscription(id);
    if (transcription) await this.#calls.deleteTranscription(transcription.id);
    await this.#calls.setStatus(id, 'UPLOADED');
  }
}

function toCall(call: ProviderCall, userName: string): Call {
  return {
    id: call.id,
    userId: call.userId,
    userName,
    clientPhone: call.clientPhone,
    direction: call.direction,
    startedAt: call.startedAt,
    durationSec: call.durationSec,
    status: call.status.value,
    error: call.status.error,
  };
}

function toFileInfo(file: ProviderFile): FileInfo {
  return { name: file.name, sizeBytes: file.sizeBytes };
}

function compare(a: string | number, b: string | number): number {
  return typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b), 'ru');
}

export const callService = new CallService(new CallClient(dataProvider), userService);
