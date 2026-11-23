import assert from 'node:assert/strict';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { after, afterEach, before, describe, it, mock } from 'node:test';
import { handleStatusRequest } from '#app/modules/data/status/api.ts';
import { StatusError } from '#app/modules/data/status/entity.ts';
import type { Status } from '#app/modules/data/status/entity.ts';
import { statusService } from '#app/modules/data/status/service.ts';

const status: Status = {
  id: 's1',
  value: 'UPLOADED',
  error: null,
  createdAt: '2026-11-01T10:00:00.000Z',
  updatedAt: '2026-11-01T10:00:00.000Z',
};

let base: string;
let server: http.Server;
let handled: boolean;

before(async () => {
  server = http.createServer(async (req, res) => {
    handled = await handleStatusRequest(req, res);
    if (!handled) res.writeHead(404).end();
  });
  await new Promise<void>((resolve) => server.listen(0, resolve));
  base = `http://localhost:${(server.address() as AddressInfo).port}`;
});
after(() => server.close());
afterEach(() => mock.restoreAll());

describe('status routes', () => {
  it('POST /statuses without a body creates the default status (201)', async () => {
    const create = mock.method(statusService, 'create', async () => status);
    const res = await fetch(`${base}/statuses`, { method: 'POST' });

    assert.equal(res.status, 201);
    assert.deepEqual((await res.json()).status, status);
    assert.deepEqual(create.mock.calls[0]?.arguments, [undefined]);
  });

  it('PATCH /statuses/:id passes the id and the new value', async () => {
    const update = mock.method(statusService, 'update', async () => ({ ...status, value: 'FAILED', error: 'x' }));
    const res = await fetch(`${base}/statuses/s1`, {
      method: 'PATCH',
      body: JSON.stringify({ value: 'FAILED', error: 'x' }),
    });

    assert.equal(res.status, 200);
    assert.deepEqual(update.mock.calls[0]?.arguments, ['s1', { value: 'FAILED', error: 'x' }]);
  });

  it('GET /statuses passes the value filter', async () => {
    const list = mock.method(statusService, 'list', async () => [status]);
    const res = await fetch(`${base}/statuses?value=FAILED`);
    assert.deepEqual((await res.json()).statuses, [status]);
    assert.deepEqual(list.mock.calls[0]?.arguments, ['FAILED']);
  });

  it('answers with the status of a StatusError', async () => {
    mock.method(statusService, 'get', async () => Promise.reject(new StatusError(404, 'Status nope not found')));
    const res = await fetch(`${base}/statuses/nope`);
    assert.equal(res.status, 404);
  });

  it('answers 400 for a body that is not JSON', async () => {
    const res = await fetch(`${base}/statuses/s1`, { method: 'PATCH', body: '{oops' });
    assert.equal(res.status, 400);
  });

  it('DELETE /statuses/:id answers 204', async () => {
    mock.method(statusService, 'delete', async () => {});
    const res = await fetch(`${base}/statuses/s1`, { method: 'DELETE' });
    assert.equal(res.status, 204);
  });

  it('leaves other routes to the caller', async () => {
    await fetch(`${base}/files`);
    assert.equal(handled, false);
  });
});
