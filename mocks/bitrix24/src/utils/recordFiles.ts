// Call recordings "on Drive", plus the download links pointing at them.
// Only the IDs are stored: voximplant.statistic.get issues them, disk.file.get and download.json
// check that an ID exists and generate the file's details on the fly.

import config from '#config' with { type: 'json' };
import type { RecordFile } from './types.ts';

/** Past MAX_STORED_IDS the oldest IDs are forgotten (disk.file.get then answers ERROR_NOT_FOUND). */
const { MAX_STORED_IDS, FIRST_FILE_ID, DURATION_SEC } = config.utils.recordFiles;

const fileIds = new Set<number>();
let nextId = FIRST_FILE_ID;

export function addRecordFile(): number {
  const id = nextId++;
  fileIds.add(id);
  if (fileIds.size > MAX_STORED_IDS) {
    const oldest = fileIds.values().next().value;
    if (oldest !== undefined) fileIds.delete(oldest);
  }
  return id;
}

/**
 * Details of an existing recording, or undefined if the ID was never issued (or was forgotten).
 * The duration depends only on the ID, so disk.file.get's SIZE matches the downloaded file.
 */
export function getRecordFile(id: number): RecordFile | undefined {
  if (!fileIds.has(id)) return undefined;
  return {
    id,
    name: `record_${id}.wav`,
    durationSec: DURATION_SEC.min + ((id * 7919) % (DURATION_SEC.max - DURATION_SEC.min + 1)),
    createdBy: '1',
    createdAtMs: Date.now(),
  };
}

/**
 * Same shape as Bitrix24's DOWNLOAD_URL: /rest/download.json?token=disk|<base64("id=<id>&_=<random>")>
 * Real tokens are also signed and tied to the caller's auth; the mock skips that.
 */
export function downloadUrl(baseUrl: string, fileId: number): string {
  const random = Math.random().toString(36).slice(2, 12);
  const token = `disk|${Buffer.from(`id=${fileId}&_=${random}`).toString('base64')}`;
  return `${baseUrl}/rest/download.json?token=${encodeURIComponent(token)}`;
}

/** Returns the file id from a download token, or null if the token is malformed. */
export function fileIdFromToken(token: string): number | null {
  const [kind, payload] = token.split('|');
  if (kind !== 'disk' || !payload) return null;
  const id = Number(new URLSearchParams(Buffer.from(payload, 'base64').toString('utf8')).get('id'));
  return Number.isInteger(id) && id > 0 ? id : null;
}
