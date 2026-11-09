import assert from 'node:assert/strict';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { after, afterEach, before, beforeEach, describe, it, mock } from 'node:test';
import { config } from '#app/config.ts';
import { handleCallRequest } from '#app/modules/call/api.ts';

const realFetch = globalThis.fetch;
const DOWNLOAD_URL = 'http://bitrix.test/download/9000';

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

// Fake Bitrix24; the test's own requests to the server go through the real fetch.
function fakeBitrix(url: URL): Response {
  if (url.pathname.endsWith('/voximplant.statistic.get')) {
    return json({
      result: [
        {
          CALL_ID: 'call-1',
          PORTAL_USER_ID: '7',
          PHONE_NUMBER: '+79001234567',
          CALL_TYPE: '1',
          CALL_START_DATE: '2026-10-01T10:00:00+03:00',
          CALL_DURATION: '95',
          CALL_FAILED_CODE: '200',
          RECORD_FILE_ID: 9000,
        },
      ],
      total: 1,
    });
  }
  if (url.pathname.endsWith('/disk.file.get')) {
    return url.searchParams.get('id') === '9000'
      ? json({ result: { NAME: 'record_9000.wav', DOWNLOAD_URL } })
      : json({ error: 'ERROR_NOT_FOUND', error_description: 'Could not find entity' }, 404);
  }
  return new Response(Buffer.from('RIFF-audio'), { headers: { 'Content-Type': 'audio/wav' } });
}

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

beforeEach(() => {
  mock.method(globalThis, 'fetch', async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    const isBitrix = url.startsWith(config.bitrixWebhookUrl) || url.startsWith('http://bitrix.test');
    return isBitrix ? fakeBitrix(new URL(url)) : realFetch(input, init);
  });
});
afterEach(() => mock.restoreAll());

describe('call routes', () => {
  it('GET /calls returns the calls', async () => {
    const res = await realFetch(`${base}/calls?from=2026-10-01`);
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.calls[0].id, 'call-1');
    assert.equal(body.calls[0].recordingId, '9000');
  });

  it('GET /calls rejects an invalid date with 400', async () => {
    const res = await realFetch(`${base}/calls?from=yesterday`);
    assert.equal(res.status, 400);
  });

  it('GET /calls answers 502 when Bitrix24 is unreachable', async () => {
    mock.restoreAll();
    mock.method(globalThis, 'fetch', async (input: string | URL | Request, init?: RequestInit) => {
      if (String(input).startsWith(config.bitrixWebhookUrl)) throw new TypeError('fetch failed');
      return realFetch(input, init);
    });
    const res = await realFetch(`${base}/calls`);
    assert.equal(res.status, 502);
  });

  it('GET /calls/recordings/:id returns the file', async () => {
    const res = await realFetch(`${base}/calls/recordings/9000`);
    assert.equal(res.status, 200);
    assert.equal(res.headers.get('content-type'), 'audio/wav');
    assert.equal(await res.text(), 'RIFF-audio');
  });

  it('GET /calls/recordings/:id answers 404 for an unknown recording', async () => {
    const res = await realFetch(`${base}/calls/recordings/1`);
    assert.equal(res.status, 404);
  });

  it('POST .../download starts a download whose status can be read', async () => {
    const started = await realFetch(`${base}/calls/recordings/1/download`, { method: 'POST' });
    assert.equal(started.status, 202);
    const { download } = await started.json();
    assert.equal(download.status, 'in_progress');

    await new Promise((resolve) => setTimeout(resolve, 50));
    const res = await realFetch(`${base}/calls/downloads/${download.id}`);
    assert.equal(res.status, 200);
    assert.equal((await res.json()).download.status, 'error');
  });

  it('GET /calls/downloads/:id answers 404 for an unknown download', async () => {
    const res = await realFetch(`${base}/calls/downloads/nope`);
    assert.equal(res.status, 404);
  });

  it('leaves other routes to the caller', async () => {
    await realFetch(`${base}/other`);
    assert.equal(handled, false);
  });
});
