/** Links a call to the file holding its transcription (a "transcription" type file with JSON). */
export type Transcription = {
  id: string;
  callId: string;
  fileId: string;
  /** ISO-8601 */
  createdAt: string;
  updatedAt: string;
};

export type CreateTranscriptionInput = {
  callId: string;
  fileId: string;
};

/** An error with the HTTP status the API answers with. */
export class TranscriptionError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
