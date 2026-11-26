import assert from 'node:assert/strict';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { after, afterEach, before, describe, it, mock } from 'node:test';
import { HttpError } from '#backend/infrastructure/http.ts';
import { handleUserRequest } from '#backend/modules/user/api.ts';
import type { User } from '#backend/modules/user/entity.ts';
import { userService } from '#backend/modules/user/service.ts';

const anna: User = { id: 'u1', name: 'Анна', email: 'anna@example.com', role: 'ADMIN' };

let base: string;
let server: http.Server;

before(async () => {
  server = http.createServer(async (req, res) => {
    if (!(await handleUserRequest(req, res))) res.writeHead(404).end();
  });
  await new Promise<void>((resolve) => server.listen(0, resolve));
  base = `http://localhost:${(server.address() as AddressInfo).port}`;
});
after(() => server.close());
afterEach(() => mock.restoreAll());

describe('user routes', () => {
  it('GET /api/me gives the current user', async () => {
    mock.method(userService, 'current', async () => anna);
    const res = await fetch(`${base}/api/me`);
    assert.deepEqual(await res.json(), { user: anna });
  });

  it('DELETE /api/users/:id deletes on behalf of the current user', async () => {
    mock.method(userService, 'current', async () => anna);
    const remove = mock.method(userService, 'delete', async () => {});
    const res = await fetch(`${base}/api/users/u2`, { method: 'DELETE' });
    assert.equal(res.status, 204);
    assert.deepEqual(remove.mock.calls[0]?.arguments, [anna, 'u2']);
  });

  it('passes on why a user cannot be deleted', async () => {
    mock.method(userService, 'current', async () => anna);
    mock.method(userService, 'delete', async () => Promise.reject(new HttpError(409, 'The user still has calls')));
    const res = await fetch(`${base}/api/users/u2`, { method: 'DELETE' });
    assert.equal(res.status, 409);
    assert.equal((await res.json()).error, 'The user still has calls');
  });
});
