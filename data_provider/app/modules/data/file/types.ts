import type { File } from './entity.ts';

/** A file with its storage location, which only the module itself needs. */
export type StoredFile = File & { uri: string };

export type FileFormat = {
  contentType: string;
  extension: string;
};
