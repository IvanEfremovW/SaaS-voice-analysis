export const FILE_TYPES = ['call_recording', 'transcription'] as const;
export type FileType = (typeof FILE_TYPES)[number];

export type File = {
  id: string;
  name: string;
  type: FileType;
  contentType: string;
  sizeBytes: number;
  /** sha256 of the content */
  checksum: string;
  /** ISO-8601 */
  createdAt: string;
  updatedAt: string;
};

export type UploadFileInput = {
  name: string;
  type: FileType;
  data: Buffer;
};

export type FileContent = {
  file: File;
  data: Buffer;
};

/** An error with the HTTP status the API answers with. */
export class FileError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
