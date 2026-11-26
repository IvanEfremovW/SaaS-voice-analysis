import type { CallStatus, Status } from '#app/modules/data/status/entity.ts';

export const CALL_DIRECTIONS = ['INCOMING', 'OUTGOING'] as const;
export type CallDirection = (typeof CALL_DIRECTIONS)[number];

export type Call = {
  id: string;
  userId: string;
  clientPhone: string;
  direction: CallDirection;
  /** ISO-8601 */
  startedAt: string;
  durationSec: number;
  /** The recording; its content is at GET /calls/:id/recording. */
  fileId: string;
  /** Current processing stage. */
  status: Status;
  createdAt: string;
  updatedAt: string;
};

export type CallMetadata = {
  userId: string;
  clientPhone: string;
  direction: CallDirection;
  /** ISO-8601 */
  startedAt: string;
  durationSec: number;
};

export type Recording = {
  /** Original file name */
  name: string;
  data: Buffer;
};

export type CreateCallInput = CallMetadata & { recording: Recording };

export type UpdateCallInput = Partial<CallMetadata>;

export type CallFilter = {
  userId?: string;
  status?: CallStatus;
  /** Calls with from <= startedAt < to, ISO-8601 */
  from?: string;
  to?: string;
};

/** An error with the HTTP status the API answers with. */
export class CallError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
