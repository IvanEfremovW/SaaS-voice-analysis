import { randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { config } from '#app/config.ts';
import { BitrixCallClient } from './client.ts';
import { CallError } from './entity.ts';
import type { Call, CallFilter, Download, Recording } from './entity.ts';
import type { BitrixCall } from './types.ts';

export class CallService {
  #client: BitrixCallClient;
  #downloadDir: string;
  #downloads = new Map<string, Download>();

  constructor(client: BitrixCallClient, downloadDir: string) {
    this.#client = client;
    this.#downloadDir = downloadDir;
  }

  async listCalls(filter: CallFilter = {}): Promise<Call[]> {
    const calls = await this.#client.listCalls(filter);
    return calls.map(toCall);
  }

  /** Downloads a recording into memory. */
  async downloadRecording(recordingId: string): Promise<Recording> {
    const file = await this.#client.getFile(recordingId);
    const { data, contentType } = await this.#client.download(file.DOWNLOAD_URL);
    return { fileName: file.NAME, contentType, data };
  }

  /** Starts saving a recording to disk; follow its status with getDownload(). */
  startDownload(recordingId: string): Download {
    const download: Download = {
      id: randomUUID(),
      recordingId,
      status: 'in_progress',
      filePath: null,
      error: null,
      startedAt: new Date().toISOString(),
      finishedAt: null,
    };
    this.#downloads.set(download.id, download);

    this.#saveRecording(recordingId)
      .then(
        (filePath) => Object.assign(download, { status: 'success', filePath }),
        (err: unknown) => Object.assign(download, { status: 'error', error: errorMessage(err) }),
      )
      .finally(() => {
        download.finishedAt = new Date().toISOString();
      });

    return { ...download };
  }

  getDownload(id: string): Download | undefined {
    const download = this.#downloads.get(id);
    return download && { ...download };
  }

  async #saveRecording(recordingId: string): Promise<string> {
    const recording = await this.downloadRecording(recordingId);
    const filePath = path.join(this.#downloadDir, `${recordingId}-${randomUUID()}${path.extname(recording.fileName)}`);
    try {
      await mkdir(this.#downloadDir, { recursive: true });
      await writeFile(filePath, recording.data, { flag: 'wx' });
    } catch (err) {
      throw new CallError(500, `Cannot save the recording to ${this.#downloadDir}: ${errorMessage(err)}`);
    }
    return filePath;
  }
}

function toCall(call: BitrixCall): Call {
  return {
    id: call.CALL_ID,
    employeeId: call.PORTAL_USER_ID,
    phoneNumber: call.PHONE_NUMBER,
    // CALL_TYPE 2 and 3 are incoming; 1 (outgoing), 4 (callback) and 5 (informational) are made by us.
    direction: call.CALL_TYPE === '2' || call.CALL_TYPE === '3' ? 'incoming' : 'outgoing',
    startedAt: call.CALL_START_DATE,
    durationSec: Number(call.CALL_DURATION),
    successful: call.CALL_FAILED_CODE === '200',
    recordingId: call.RECORD_FILE_ID === null ? null : String(call.RECORD_FILE_ID),
  };
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export const callService = new CallService(new BitrixCallClient(config.bitrixWebhookUrl), config.downloadDir);
