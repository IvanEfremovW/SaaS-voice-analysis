import type { TaskStatus, TaskType } from './entity.ts';

export type NewTask = {
  callId: string;
  type: TaskType;
  metadata: Record<string, unknown>;
};

/** What changes when a task moves on. */
export type TaskChange = {
  status: TaskStatus;
  error: string | null;
  startedAt?: Date;
  finishedAt?: Date;
};
