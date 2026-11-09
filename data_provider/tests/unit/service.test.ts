import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { after, before, describe, it } from 'node:test';
import { BitrixCallClient } from '#app/modules/call/client.ts';
import { CallError } from '#app/modules/call/entity.ts';
import type { CallFilter, Download } from '#app/modules/call/entity.ts';
import { CallService } from '#app/modules/call/service.ts';
import type { BitrixCall, BitrixDiskFile } from '#app/modules/call/types.ts';

const bitrixCall: BitrixCall = {
  CALL_ID: 'call-1',
  PORTAL_USER_ID: '7',
  PHONE_NUMBER: '+79001234567',
  CALL_TYPE: '3',
  CALL_START_DATE: '2026-10-01T10:00:00+03:00',
  CALL_DURATION: '95',
  CALL_FAILED_CODE: '200',
  RECORD_FILE_ID: 9000,
};

class FakeClient extends BitrixCallClient {
  calls: BitrixCall[] = [bitrixCall];

  constructor() {
    super('http://bitrix.test');
  }

  override async listCalls(_filter: CallFilter): Promise<BitrixCall[]> {
    return this.calls;
  }

  override async getFile(fileId: string): Promise<BitrixDiskFile> {
    if (fileId !== '9000') throw new CallError(404, 'ERROR_NOT_FOUND: Could not find entity');
    return { NAME: 'record_9000.wav', DOWNLOAD_URL: 'http://bitrix.test/download' };
  }

  override async download(): Promise<{ data: Buffer; contentType: string }> {
    return { data: Buffer.from('RIFF-audio'), contentType: 'audio/wav' };
  }
}

async function waitUntilFinished(service: CallService, id: string): Promise<Download> {
  for (let i = 0; i < 100; i++) {
    const download = service.getDownload(id);
    if (download && download.status !== 'in_progress') return download;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`Download ${id} did not finish`);
}

let dir: string;
before(async () => {
  dir = await mkdtemp(path.join(tmpdir(), 'data-provider-'));
});
after(() => rm(dir, { recursive: true, force: true }));

describe('CallService.listCalls', () => {
  it('maps Bitrix24 calls to Call', async () => {
    const client = new FakeClient();
    client.calls = [bitrixCall, { ...bitrixCall, CALL_TYPE: '4', CALL_FAILED_CODE: '304', RECORD_FILE_ID: null }];

    const calls = await new CallService(client, dir).listCalls();

    assert.deepEqual(calls[0], {
      id: 'call-1',
      employeeId: '7',
      phoneNumber: '+79001234567',
      direction: 'incoming',
      startedAt: '2026-10-01T10:00:00+03:00',
      durationSec: 95,
      successful: true,
      recordingId: '9000',
    });
    assert.equal(calls[1]?.direction, 'outgoing');
    assert.equal(calls[1]?.successful, false);
    assert.equal(calls[1]?.recordingId, null);
  });
});

describe('CallService.startDownload', () => {
  it('saves the recording under a unique name and reports success', async () => {
    const service = new CallService(new FakeClient(), dir);

    const first = service.startDownload('9000');
    const second = service.startDownload('9000');
    assert.equal(first.status, 'in_progress');

    const done = [await waitUntilFinished(service, first.id), await waitUntilFinished(service, second.id)];
    for (const download of done) {
      assert.equal(download.status, 'success');
      assert.ok(download.finishedAt);
      assert.equal(await readFile(download.filePath ?? '', 'utf8'), 'RIFF-audio');
    }
    assert.notEqual(done[0]?.filePath, done[1]?.filePath);
    assert.match(path.basename(done[0]?.filePath ?? ''), /^9000-.+\.wav$/);
  });

  it('reports an error when the recording does not exist', async () => {
    const service = new CallService(new FakeClient(), dir);
    const download = await waitUntilFinished(service, service.startDownload('1').id);
    assert.equal(download.status, 'error');
    assert.match(download.error ?? '', /ERROR_NOT_FOUND/);
    assert.equal(download.filePath, null);
  });

  it('reports an error when the folder cannot be written', async () => {
    const notADir = path.join(dir, 'file.txt');
    await writeFile(notADir, '');
    const service = new CallService(new FakeClient(), path.join(notADir, 'downloads'));

    const download = await waitUntilFinished(service, service.startDownload('9000').id);

    assert.equal(download.status, 'error');
    assert.match(download.error ?? '', /Cannot save the recording/);
  });

  it('returns undefined for an unknown download', () => {
    assert.equal(new CallService(new FakeClient(), dir).getDownload('nope'), undefined);
  });
});
