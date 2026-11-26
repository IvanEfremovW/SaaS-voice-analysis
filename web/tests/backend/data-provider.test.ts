import assert from 'node:assert/strict';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { after, before, describe, it } from 'node:test';
import { DataProvider } from '#backend/infrastructure/data-provider.ts';
import type { HttpError } from '#backend/infrastructure/http.ts';

// A stand-in for data_provider that answers with what the test asks for in the path.
let dataProvider: DataProvider;
let server: http.Server;
let lastRequest: { method?: string | undefined; url?: string | undefined; body: string };

before(async () => {
  server = http.createServer(async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    lastRequest = { method: req.method, url: req.url, body };
    const status = Number(req.url?.split('/')[1]?.split('?')[0]);
    if (status === 204) return res.writeHead(204).end();
    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(status < 400 ? { ok: true } : { error: `failed with ${status}` }));
  });
  await new Promise<void>((resolve) => server.listen(0, resolve));
  dataProvider = new DataProvider(`http://localhost:${(server.address() as AddressInfo).port}`);
});
after(() => server.close());

describe('DataProvider', () => {
  it('sends the query without empty values and gives the JSON answer', async () => {
    assert.deepEqual(await dataProvider.get('/200', { userId: 'u1', from: undefined }), { ok: true });
    assert.equal(lastRequest.url, '/200?userId=u1');
  });

  it('sends a JSON body; an empty answer is undefined', async () => {
    assert.equal(await dataProvider.send('PATCH', '/204', { value: 'UPLOADED' }), undefined);
    assert.deepEqual(lastRequest, { method: 'PATCH', url: '/204', body: '{"value":"UPLOADED"}' });
  });

  it('passes on request errors and turns its own failures into 502', async () => {
    await assert.rejects(dataProvider.get('/409'), (err: HttpError) => err.status === 409 && err.message === 'failed with 409');
    await assert.rejects(dataProvider.get('/500'), (err: HttpError) => err.status === 502);
  });
});
