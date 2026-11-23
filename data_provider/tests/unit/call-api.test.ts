import assert from 'node:assert/strict';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { after, afterEach, before, describe, it, mock } from 'node:test';
import { handleCallRequest } from '#app/modules/data/call/api.ts';
import type { Call } from '#app/modules/data/call/entity.ts';
import { callService } from '#app/modules/data/call/service.ts';
import { FileError } from '#app/modules/data/file/entity.ts';
import type { File } from '#app/modules/data/file/entity.ts';

const call = { id: 'c1', fileId: 'f1' } as Call;

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
  it('POST /calls takes the metadata from the query and the recording from the body', async () => {
    const create = mock.method(callService, 'create', async () => call);
    const query = new URLSearchParams({
      userId: 'u1',
      clientPhone: '+79001234567',
      direction: 'INCOMING',
      startedAt: '2026-11-01T09:00:00+03:00',
      durationSec: '95',
      name: 'call.wav',
    });
    const res = await fetch(`${base}/calls?${query}`, { method: 'POST', body: Buffer.from('RIFF') });

    assert.equal(res.status, 201);
    const input = create.mock.calls[0]?.arguments[0];
    assert.equal(input?.clientPhone, '+79001234567');
    assert.equal(input?.startedAt, '2026-11-01T09:00:00+03:00');
    assert.equal(input?.durationSec, 95);
    assert.equal(input?.recording.name, 'call.wav');
    assert.equal(input?.recording.data.toString(), 'RIFF');
  });

  it('answers with the status of errors from other modules, e.g. a rejected recording', async () => {
    mock.method(callService, 'create', async () => Promise.reject(new FileError(400, 'Unsupported format for a call_recording file')));
    const res = await fetch(`${base}/calls?userId=u1`, { method: 'POST', body: 'text' });
    assert.equal(res.status, 400);
    assert.equal((await res.json()).error, 'Unsupported format for a call_recording file');
  });

  it('GET /calls passes the filters', async () => {
    const list = mock.method(callService, 'list', async () => [call]);
    await fetch(`${base}/calls?userId=u1&status=FAILED&from=2026-11-01`);
    assert.deepEqual(list.mock.calls[0]?.arguments[0], { userId: 'u1', status: 'FAILED', from: '2026-11-01' });
  });

  it('GET /calls/:id/recording returns the audio', async () => {
    const file = { name: 'call.wav', contentType: 'audio/wav' } as File;
    mock.method(callService, 'downloadRecording', async () => ({ file, data: Buffer.from('RIFF') }));
    const res = await fetch(`${base}/calls/c1/recording`);
    assert.equal(res.headers.get('content-type'), 'audio/wav');
    assert.equal(await res.text(), 'RIFF');
  });

  it('PUT /calls/:id/recording replaces the recording', async () => {
    const replace = mock.method(callService, 'replaceRecording', async () => call);
    const res = await fetch(`${base}/calls/c1/recording?name=new.wav`, { method: 'PUT', body: Buffer.from('RIFF') });
    assert.equal(res.status, 200);
    assert.equal(replace.mock.calls[0]?.arguments[0], 'c1');
    assert.equal(replace.mock.calls[0]?.arguments[1]?.name, 'new.wav');
  });

  it('PATCH /calls/:id and /calls/:id/status pass the JSON body', async () => {
    const update = mock.method(callService, 'update', async () => call);
    const updateStatus = mock.method(callService, 'updateStatus', async () => ({}) as never);

    await fetch(`${base}/calls/c1`, { method: 'PATCH', body: JSON.stringify({ durationSec: 100 }) });
    await fetch(`${base}/calls/c1/status`, { method: 'PATCH', body: JSON.stringify({ value: 'TRANSCRIBING' }) });

    assert.deepEqual(update.mock.calls[0]?.arguments, ['c1', { durationSec: 100 }]);
    assert.deepEqual(updateStatus.mock.calls[0]?.arguments, ['c1', { value: 'TRANSCRIBING' }]);
  });

  it('DELETE /calls/:id answers 204', async () => {
    mock.method(callService, 'delete', async () => {});
    const res = await fetch(`${base}/calls/c1`, { method: 'DELETE' });
    assert.equal(res.status, 204);
  });

  it('leaves other routes to the caller', async () => {
    await fetch(`${base}/users`);
    assert.equal(handled, false);
  });
});
