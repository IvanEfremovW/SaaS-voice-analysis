import assert from 'node:assert/strict';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { after, afterEach, before, describe, it, mock } from 'node:test';
import type { File } from '#app/modules/data/file/entity.ts';
import { handleTranscriptionRequest } from '#app/modules/data/transcription/api.ts';
import { TranscriptionError } from '#app/modules/data/transcription/entity.ts';
import type { Transcription } from '#app/modules/data/transcription/entity.ts';
import { transcriptionService } from '#app/modules/data/transcription/service.ts';

const transcription: Transcription = {
  id: 't1',
  callId: 'c1',
  fileId: 'f1',
  createdAt: '2026-11-01T10:00:00.000Z',
  updatedAt: '2026-11-01T10:00:00.000Z',
};

let base: string;
let server: http.Server;
let handled: boolean;

before(async () => {
  server = http.createServer(async (req, res) => {
    handled = await handleTranscriptionRequest(req, res);
    if (!handled) res.writeHead(404).end();
  });
  await new Promise<void>((resolve) => server.listen(0, resolve));
  base = `http://localhost:${(server.address() as AddressInfo).port}`;
});
after(() => server.close());
afterEach(() => mock.restoreAll());

describe('transcription routes', () => {
  it('POST /transcriptions passes callId and fileId (201)', async () => {
    const create = mock.method(transcriptionService, 'create', async () => transcription);
    const res = await fetch(`${base}/transcriptions`, {
      method: 'POST',
      body: JSON.stringify({ callId: 'c1', fileId: 'f1' }),
    });
    assert.equal(res.status, 201);
    assert.deepEqual(create.mock.calls[0]?.arguments, [{ callId: 'c1', fileId: 'f1' }]);
  });

  it('GET /transcriptions passes the callId filter', async () => {
    const list = mock.method(transcriptionService, 'list', async () => [transcription]);
    const res = await fetch(`${base}/transcriptions?callId=c1`);
    assert.deepEqual((await res.json()).transcriptions, [transcription]);
    assert.deepEqual(list.mock.calls[0]?.arguments, ['c1']);
  });

  it('GET /transcriptions/:id/content returns the JSON file', async () => {
    const file = { contentType: 'application/json' } as File;
    mock.method(transcriptionService, 'content', async () => ({ file, data: Buffer.from('{"text":"hi"}') }));
    const res = await fetch(`${base}/transcriptions/t1/content`);
    assert.equal(res.headers.get('content-type'), 'application/json');
    assert.deepEqual(await res.json(), { text: 'hi' });
  });

  it('answers with the status of a TranscriptionError', async () => {
    mock.method(transcriptionService, 'create', async () =>
      Promise.reject(new TranscriptionError(409, 'Call c1 already has transcription t1')),
    );
    const res = await fetch(`${base}/transcriptions`, { method: 'POST', body: '{}' });
    assert.equal(res.status, 409);
  });

  it('DELETE /transcriptions/:id answers 204', async () => {
    mock.method(transcriptionService, 'delete', async () => {});
    const res = await fetch(`${base}/transcriptions/t1`, { method: 'DELETE' });
    assert.equal(res.status, 204);
  });

  it('leaves other routes to the caller', async () => {
    await fetch(`${base}/statuses`);
    assert.equal(handled, false);
  });
});
