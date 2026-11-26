// What the backend gives to the pages. The frontend imports these types (types only, never code).

export type CallStatus = 'UPLOADED' | 'TRANSCRIBING' | 'TRANSCRIBED' | 'ANALYZING' | 'ANALYZED' | 'FAILED';
export type CallDirection = 'INCOMING' | 'OUTGOING';

export type Call = {
  id: string;
  userId: string;
  /** Name of the employee who had the call. */
  userName: string;
  clientPhone: string;
  direction: CallDirection;
  /** ISO-8601 */
  startedAt: string;
  durationSec: number;
  status: CallStatus;
  /** Why processing failed; set only when status is FAILED. */
  error: string | null;
};

export type FileInfo = {
  name: string;
  sizeBytes: number;
};

/** One call with everything its page shows. */
export type CallDetails = Call & {
  /** Its content is at GET /api/calls/:id/recording */
  recording: FileInfo;
  /** Its content is at GET /api/calls/:id/transcription; null if the call has none. */
  transcription: { createdAt: string; file: FileInfo } | null;
};

/** The columns the list can be sorted by. */
export type CallSort = 'startedAt' | 'userName' | 'clientPhone' | 'direction' | 'durationSec' | 'status';

export type CallQuery = {
  userId?: string;
  direction?: CallDirection;
  /** Calls with from <= startedAt < to, ISO-8601 */
  from?: string;
  to?: string;
  /** startedAt if not given */
  sort?: CallSort;
  /** desc if not given */
  order?: 'asc' | 'desc';
};
