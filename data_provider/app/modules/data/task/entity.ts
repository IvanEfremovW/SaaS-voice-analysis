export const TASK_TYPES = ['TRANSCRIPTION', 'ANALYSIS'] as const;
export type TaskType = (typeof TASK_TYPES)[number];

/** QUEUED -> RUNNING -> SUCCEEDED or FAILED */
export const TASK_STATUSES = ['QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED'] as const;
export type TaskStatus = (typeof TASK_STATUSES)[number];

/** One run of a processing step (transcription or analysis) of a call. */
export type Task = {
  id: string;
  callId: string;
  type: TaskType;
  status: TaskStatus;
  /** Settings of this run, in whatever shape the module doing it needs; {} if none. */
  metadata: Record<string, unknown>;
  /** Why the run failed; set only when status is FAILED. */
  error: string | null;
  /** ISO-8601; when a worker took the task, null until then */
  startedAt: string | null;
  /** When it SUCCEEDED or FAILED */
  finishedAt: string | null;
  createdAt: string;
  updatedAt: string;
};

export type CreateTaskInput = {
  callId: string;
  type: TaskType;
  metadata?: Record<string, unknown>;
};

export type UpdateTaskInput = {
  status: TaskStatus;
  /** Required when status is FAILED, not allowed otherwise. */
  error?: string;
};

export type TaskFilter = {
  callId?: string;
  type?: TaskType;
  status?: TaskStatus;
};

/** An error with the HTTP status the API answers with. */
export class TaskError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
