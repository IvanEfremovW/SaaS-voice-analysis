import assert from 'node:assert/strict';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { after, afterEach, before, describe, it, mock } from 'node:test';
import { handleFileRequest } from '#app/modules/data/file/api.ts';
import { FileError } from '#app/modules/data/file/entity.ts';
import type { File } from '#app/modules/data/file/entity.ts';
import { fileService } from '#app/modules/data/file/service.ts';

const file: File = {
  id: 'f1',
  name: 'звонок.wav',
  type: 'call_recording',
  contentType: 'audio/wav',
  sizeBytes: 4,
  checksum: 'abc',
  createdAt: '2026-11-01T10:00:00.000Z',
  updatedAt: '2026-11-01T10:00:00.000Z',
};

let base: string;
let server: http.Server;
let handled: boolean;

before(async () => {
  server = http.createServer(async (req, res) => {
    handled = await handleFileRequest(req, res);
    if (!handled) res.writeHead(404).end();
  });
  await new Promise<void>((resolve) => server.listen(0, resolve));
  base = `http://localhost:${(server.address() as AddressInfo).port}`;
});
after(() => server.close());
afterEach(() => mock.restoreAll());

describe('file routes', () => {
  it('POST /files passes name, type and the body bytes (201)', async () => {
    const upload = mock.method(fileService, 'upload', async () => file);
    const res = await fetch(`${base}/files?type=call_recording&name=${encodeURIComponent('звонок.wav')}`, {
      method: 'POST',
      body: Buffer.from('RIFF'),
    });

    assert.equal(res.status, 201);
    assert.deepEqual((await res.json()).file, file);
    const input = upload.mock.calls[0]?.arguments[0];
    assert.equal(input?.name, 'звонок.wav');
    assert.equal(input?.type, 'call_recording');
    assert.equal(input?.data.toString(), 'RIFF');
  });

  it('answers with the status of a FileError', async () => {
    mock.method(fileService, 'upload', async () => Promise.reject(new FileError(409, 'The same file is already stored as f1')));
    const res = await fetch(`${base}/files?type=call_recording&name=a.wav`, { method: 'POST', body: 'RIFF' });
    assert.equal(res.status, 409);
    assert.equal((await res.json()).error, 'The same file is already stored as f1');
  });

  it('GET /files passes the type filter', async () => {
    const list = mock.method(fileService, 'list', async () => [file]);
    const res = await fetch(`${base}/files?type=transcription`);
    assert.deepEqual((await res.json()).files, [file]);
    assert.deepEqual(list.mock.calls[0]?.arguments, ['transcription']);
  });

  it('GET /files/:id/content returns the bytes with type and file name', async () => {
    mock.method(fileService, 'download', async () => ({ file, data: Buffer.from('RIFF') }));
    const res = await fetch(`${base}/files/f1/content`);

    assert.equal(res.status, 200);
    assert.equal(res.headers.get('content-type'), 'audio/wav');
    assert.match(res.headers.get('content-disposition') ?? '', /filename\*=UTF-8''%D0%B7%D0%B2%D0%BE%D0%BD%D0%BE%D0%BA\.wav/);
    assert.equal(await res.text(), 'RIFF');
  });

  it('DELETE /files/:id answers 204', async () => {
    mock.method(fileService, 'delete', async () => {});
    const res = await fetch(`${base}/files/f1`, { method: 'DELETE' });
    assert.equal(res.status, 204);
  });

  it('leaves other routes to the caller', async () => {
    await fetch(`${base}/users`);
    assert.equal(handled, false);
  });
});
