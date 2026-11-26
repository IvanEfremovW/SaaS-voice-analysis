/** Processing stages of a call, in order; FAILED can happen at any stage. */
export const CALL_STATUSES = ['UPLOADED', 'TRANSCRIBING', 'TRANSCRIBED', 'ANALYZING', 'ANALYZED', 'FAILED'] as const;
export type CallStatus = (typeof CALL_STATUSES)[number];

export type Status = {
  id: string;
  value: CallStatus;
  /** Why processing failed; set only when value is FAILED. */
  error: string | null;
  /** ISO-8601 */
  createdAt: string;
  /** When the value last changed. */
  updatedAt: string;
};

export type UpdateStatusInput = {
  value: CallStatus;
  /** Required when value is FAILED, not allowed otherwise. */
  error?: string;
};

/** An error with the HTTP status the API answers with. */
export class StatusError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
