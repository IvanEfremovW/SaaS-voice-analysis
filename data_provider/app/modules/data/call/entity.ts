export type Call = {
  id: string;
  employeeId: string;
  phoneNumber: string;
  direction: 'incoming' | 'outgoing';
  /** ISO-8601 with timezone, e.g. "2026-09-19T13:33:40+03:00". */
  startedAt: string;
  durationSec: number;
  /** False for missed, declined, busy, ... calls. */
  successful: boolean;
  /** Null if the call has no recording. */
  recordingId: string | null;
};

/** Calls with from <= startedAt < to, both ISO-8601. */
export type CallFilter = {
  from?: string;
  to?: string;
};

export type Recording = {
  fileName: string;
  contentType: string;
  data: Buffer;
};

export type DownloadStatus = 'in_progress' | 'success' | 'error';

/** A recording being saved to disk. */
export type Download = {
  id: string;
  recordingId: string;
  status: DownloadStatus;
  /** Set when status is "success". */
  filePath: string | null;
  /** Set when status is "error". */
  error: string | null;
  startedAt: string;
  finishedAt: string | null;
};

/** An error with the HTTP status the API answers with. */
export class CallError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
