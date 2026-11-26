import assert from 'node:assert/strict';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { after, afterEach, before, describe, it, mock } from 'node:test';
import { HttpError } from '#backend/infrastructure/http.ts';
import { handleCallRequest } from '#backend/modules/call/api.ts';
import type { Call } from '#backend/modules/call/entity.ts';
import { callService } from '#backend/modules/call/service.ts';

let base: string;
let server: http.Server;
let handled: boolean;

before(async () => {
  server = http.createServer(async (req, res) => {
    handled = await handleCallRequest(req, res);
    if (!handled) res.writeHead(404).end();
  });
  await new Promise<void>((resolve) => server.listen(0, resolve));
  base = `http://localhost:${(server.address() as AddressInfo).port}`;
});
after(() => server.close());
afterEach(() => mock.restoreAll());

describe('call routes', () => {
  it('GET /api/calls passes the filled query fields on', async () => {
    const list = mock.method(callService, 'list', async () => [{ id: 'c1' } as Call]);
    const res = await fetch(`${base}/api/calls?userId=u1&direction=&sort=durationSec&order=asc`);
    assert.equal(res.status, 200);
    assert.deepEqual(await res.json(), { calls: [{ id: 'c1' }] });
    assert.deepEqual(list.mock.calls[0]?.arguments, [{ userId: 'u1', sort: 'durationSec', order: 'asc' }]);
  });

  it('answers with the status of an HttpError', async () => {
    mock.method(callService, 'get', async () => Promise.reject(new HttpError(404, 'Call c9 not found')));
    const res = await fetch(`${base}/api/calls/c9`);
    assert.equal(res.status, 404);
    assert.equal((await res.json()).error, 'Call c9 not found');
  });

  it('hides the details of unexpected errors', async () => {
    mock.method(console, 'error', () => {});
    mock.method(callService, 'list', async () => Promise.reject(new Error('connect ECONNREFUSED')));
    const res = await fetch(`${base}/api/calls`);
    assert.equal(res.status, 500);
    assert.equal((await res.json()).error, 'Internal server error');
  });

  it('GET /api/calls/:id/recording streams the file with its name', async () => {
    const disposition = `attachment; filename="call.wav"`;
    mock.method(callService, 'downloadRecording', async () => {
      return new Response('RIFF', { headers: { 'Content-Type': 'audio/wav', 'Content-Disposition': disposition } });
    });
    const res = await fetch(`${base}/api/calls/c1/recording`);
    assert.equal(res.status, 200);
    assert.equal(res.headers.get('content-type'), 'audio/wav');
    assert.equal(res.headers.get('content-disposition'), disposition);
    assert.equal(await res.text(), 'RIFF');
  });

  it('POST /api/calls/:id/transcription asks for a new transcription', async () => {
    const request = mock.method(callService, 'requestTranscription', async () => {});
    const res = await fetch(`${base}/api/calls/c1/transcription`, { method: 'POST' });
    assert.equal(res.status, 204);
    assert.deepEqual(request.mock.calls[0]?.arguments, ['c1']);
  });

  it('leaves other routes to the caller', async () => {
    await fetch(`${base}/api/users`);
    assert.equal(handled, false);
  });
});
