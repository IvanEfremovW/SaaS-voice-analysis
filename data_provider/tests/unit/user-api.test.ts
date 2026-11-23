import assert from 'node:assert/strict';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { after, afterEach, before, describe, it, mock } from 'node:test';
import { handleUserRequest } from '#app/modules/data/user/api.ts';
import { UserError } from '#app/modules/data/user/entity.ts';
import type { User } from '#app/modules/data/user/entity.ts';
import { userService } from '#app/modules/data/user/service.ts';

const user: User = {
  id: 'u1',
  name: 'Anna',
  email: 'anna@example.com',
  role: 'USER',
  createdAt: '2026-11-01T10:00:00.000Z',
  updatedAt: '2026-11-01T10:00:00.000Z',
};

let base: string;
let server: http.Server;
let handled: boolean;

before(async () => {
  server = http.createServer(async (req, res) => {
    handled = await handleUserRequest(req, res);
    if (!handled) res.writeHead(404).end();
  });
  await new Promise<void>((resolve) => server.listen(0, resolve));
  base = `http://localhost:${(server.address() as AddressInfo).port}`;
});
after(() => server.close());
afterEach(() => mock.restoreAll());

const post = (path: string, body: string) =>
  fetch(`${base}${path}`, { method: 'POST', body, headers: { 'Content-Type': 'application/json' } });

describe('user routes', () => {
  it('POST /users creates a user (201)', async () => {
    const create = mock.method(userService, 'create', async () => user);
    const res = await post('/users', JSON.stringify({ name: 'Anna', email: 'anna@example.com' }));

    assert.equal(res.status, 201);
    assert.deepEqual((await res.json()).user, user);
    assert.deepEqual(create.mock.calls[0]?.arguments[0], { name: 'Anna', email: 'anna@example.com' });
  });

  it('POST /users answers 400 for a body that is not JSON', async () => {
    const res = await post('/users', '{oops');
    assert.equal(res.status, 400);
  });

  it('GET /users lists users', async () => {
    mock.method(userService, 'list', async () => [user]);
    const res = await fetch(`${base}/users`);
    assert.deepEqual((await res.json()).users, [user]);
  });

  it('GET /users/:id answers with the status of a UserError', async () => {
    mock.method(userService, 'get', async () => Promise.reject(new UserError(404, 'User nope not found')));
    const res = await fetch(`${base}/users/nope`);
    assert.equal(res.status, 404);
    assert.equal((await res.json()).error, 'User nope not found');
  });

  it('PATCH /users/:id passes the id and the changes', async () => {
    const update = mock.method(userService, 'update', async () => ({ ...user, role: 'ADMIN' }));
    const res = await fetch(`${base}/users/u1`, { method: 'PATCH', body: JSON.stringify({ role: 'ADMIN' }) });

    assert.equal(res.status, 200);
    assert.deepEqual(update.mock.calls[0]?.arguments, ['u1', { role: 'ADMIN' }]);
  });

  it('DELETE /users/:id answers 204', async () => {
    mock.method(userService, 'delete', async () => {});
    const res = await fetch(`${base}/users/u1`, { method: 'DELETE' });
    assert.equal(res.status, 204);
  });

  it('hides the details of unexpected errors (500)', async () => {
    mock.method(console, 'error', () => {});
    mock.method(userService, 'list', async () => Promise.reject(new Error('connection refused at 10.0.0.5')));
    const res = await fetch(`${base}/users`);
    assert.equal(res.status, 500);
    assert.equal((await res.json()).error, 'Internal server error');
  });

  it('leaves other routes to the caller', async () => {
    await fetch(`${base}/other`);
    assert.equal(handled, false);
  });
});
