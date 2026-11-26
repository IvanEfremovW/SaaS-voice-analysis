import { database } from '#app/infrastructure/database.ts';
import { CallError } from '#app/modules/data/call/entity.ts';
import { callService } from '#app/modules/data/call/service.ts';
import type { CallService } from '#app/modules/data/call/service.ts';
import type { CallStatus } from '#app/modules/data/status/entity.ts';
import { transcriptionService } from '#app/modules/data/transcription/service.ts';
import type { TranscriptionService } from '#app/modules/data/transcription/service.ts';
import { TASK_STATUSES, TASK_TYPES, TaskError } from './entity.ts';
import type { CreateTaskInput, Task, TaskFilter, TaskStatus, TaskType, UpdateTaskInput } from './entity.ts';
import { TaskRepository } from './repository.ts';

// Where a task may go from each status. RUNNING -> RUNNING: a run cut off by a dying worker is
// delivered to a worker again and starts over.
const NEXT: Record<TaskStatus, TaskStatus[]> = {
  QUEUED: ['RUNNING', 'FAILED'],
  RUNNING: ['RUNNING', 'SUCCEEDED', 'FAILED'],
  SUCCEEDED: [],
  FAILED: [],
};

// The stage the call moves to when its task of this type moves to this status.
const CALL_STAGE: Record<TaskType, Partial<Record<TaskStatus, CallStatus>>> = {
  TRANSCRIPTION: { RUNNING: 'TRANSCRIBING', SUCCEEDED: 'TRANSCRIBED', FAILED: 'FAILED' },
  ANALYSIS: { RUNNING: 'ANALYZING', SUCCEEDED: 'ANALYZED', FAILED: 'FAILED' },
};

export class TaskService {
  #tasks: TaskRepository;
  #calls: CallService;
  #transcriptions: TranscriptionService;

  constructor(tasks: TaskRepository, calls: CallService, transcriptions: TranscriptionService) {
    this.#tasks = tasks;
    this.#calls = calls;
    this.#transcriptions = transcriptions;
  }

  /**
   * Asks for a new run; a call has at most one unfinished task. A new transcription replaces the old one:
   * the old one is deleted and the call goes back to UPLOADED. An analysis needs a transcription,
   * and the call goes back to TRANSCRIBED.
   */
  async create(input: CreateTaskInput): Promise<Task> {
    if (typeof input !== 'object' || input === null) throw new TaskError(400, 'Body must be a JSON object');
    const { callId, type, metadata = {} } = input;
    if (typeof callId !== 'string' || !callId) throw new TaskError(400, '"callId" must be a non-empty string');
    checkType(type);
    if (typeof metadata !== 'object' || metadata === null || Array.isArray(metadata)) {
      throw new TaskError(400, '"metadata" must be a JSON object');
    }

    await this.#calls.get(callId).catch((err) => {
      throw err instanceof CallError && err.status === 404 ? new TaskError(400, `Call ${callId} does not exist`) : err;
    });
    const unfinished = await this.#tasks.findUnfinished(callId);
    if (unfinished) throw new TaskError(409, `Call ${callId} already has an unfinished task ${unfinished.id}`);

    const transcriptions = await this.#transcriptions.list(callId);
    if (type === 'TRANSCRIPTION') {
      for (const transcription of transcriptions) await this.#transcriptions.delete(transcription.id);
      await this.#calls.updateStatus(callId, { value: 'UPLOADED' });
    } else {
      if (transcriptions.length === 0) throw new TaskError(409, `Call ${callId} has no transcription to analyse`);
      await this.#calls.updateStatus(callId, { value: 'TRANSCRIBED' });
    }
    return this.#tasks.create({ callId, type, metadata });
  }

  async get(id: string): Promise<Task> {
    return (await this.#tasks.findById(id)) ?? notFound(id);
  }

  async list(filter: TaskFilter = {}): Promise<Task[]> {
    if (filter.type !== undefined) checkType(filter.type);
    if (filter.status !== undefined) checkStatus(filter.status);
    return this.#tasks.list(filter);
  }

  /** Moves the task on (done by the worker running it), and the call to the matching stage. */
  async update(id: string, input: UpdateTaskInput): Promise<Task> {
    if (typeof input !== 'object' || input === null) throw new TaskError(400, 'Body must be a JSON object');
    const status = checkStatus(input.status);
    let error: string | null = null;
    if (status === 'FAILED') {
      if (typeof input.error !== 'string' || !input.error.trim()) {
        throw new TaskError(400, '"error" must describe why the task FAILED');
      }
      error = input.error.trim();
    } else if (input.error !== undefined) {
      throw new TaskError(400, '"error" is only allowed with FAILED');
    }

    const task = await this.get(id);
    if (!NEXT[task.status].includes(status)) {
      throw new TaskError(409, `Task ${id} can't go from ${task.status} to ${status}`);
    }
    if (task.type === 'TRANSCRIPTION' && status === 'SUCCEEDED' && (await this.#transcriptions.list(task.callId)).length === 0) {
      throw new TaskError(409, `Save the transcription of call ${task.callId} (POST /transcriptions) before the task succeeds`);
    }

    const now = new Date();
    const updated =
      (await this.#tasks.update(id, {
        status,
        error,
        ...(status === 'RUNNING' && { startedAt: now }),
        ...((status === 'SUCCEEDED' || status === 'FAILED') && { finishedAt: now }),
      })) ?? notFound(id);

    const stage = CALL_STAGE[task.type][status];
    if (stage) await this.#calls.updateStatus(task.callId, { value: stage, ...(error !== null && { error }) });
    return updated;
  }
}

function checkType(type: unknown): TaskType {
  if (!TASK_TYPES.includes(type as TaskType)) throw new TaskError(400, `"type" must be one of ${TASK_TYPES.join(', ')}`);
  return type as TaskType;
}

function checkStatus(status: unknown): TaskStatus {
  if (!TASK_STATUSES.includes(status as TaskStatus)) {
    throw new TaskError(400, `"status" must be one of ${TASK_STATUSES.join(', ')}`);
  }
  return status as TaskStatus;
}

function notFound(id: string): never {
  throw new TaskError(404, `Task ${id} not found`);
}

export const taskService = new TaskService(new TaskRepository(database), callService, transcriptionService);
