import assert from 'node:assert/strict';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { after, afterEach, before, describe, it, mock } from 'node:test';
import { CallError } from '#app/modules/data/call/entity.ts';
import { handleTaskRequest } from '#app/modules/data/task/api.ts';
import { TaskError } from '#app/modules/data/task/entity.ts';
import type { Task } from '#app/modules/data/task/entity.ts';
import { taskService } from '#app/modules/data/task/service.ts';

const task: Task = {
  id: 't1',
  callId: 'c1',
  type: 'TRANSCRIPTION',
  status: 'QUEUED',
  metadata: {},
  error: null,
  startedAt: null,
  finishedAt: null,
  createdAt: '2026-11-01T10:00:00.000Z',
  updatedAt: '2026-11-01T10:00:00.000Z',
};

let base: string;
let server: http.Server;
let handled: boolean;

before(async () => {
  server = http.createServer(async (req, res) => {
    handled = await handleTaskRequest(req, res);
    if (!handled) res.writeHead(404).end();
  });
  await new Promise<void>((resolve) => server.listen(0, resolve));
  base = `http://localhost:${(server.address() as AddressInfo).port}`;
});
after(() => server.close());
afterEach(() => mock.restoreAll());

const send = (method: string, path: string, body: unknown) =>
  fetch(`${base}${path}`, { method, body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } });

describe('task routes', () => {
  it('POST /tasks creates a task (201)', async () => {
    const create = mock.method(taskService, 'create', async () => task);
    const res = await send('POST', '/tasks', { callId: 'c1', type: 'TRANSCRIPTION' });
    assert.equal(res.status, 201);
    assert.deepEqual((await res.json()).task, task);
    assert.deepEqual(create.mock.calls[0]?.arguments, [{ callId: 'c1', type: 'TRANSCRIPTION' }]);
  });

  it('GET /tasks passes the filter', async () => {
    const list = mock.method(taskService, 'list', async () => [task]);
    const res = await fetch(`${base}/tasks?callId=c1&status=QUEUED&other=x`);
    assert.deepEqual((await res.json()).tasks, [task]);
    assert.deepEqual(list.mock.calls[0]?.arguments, [{ callId: 'c1', status: 'QUEUED' }]);
  });

  it('PATCH /tasks/:id passes the id and the change', async () => {
    const update = mock.method(taskService, 'update', async () => ({ ...task, status: 'RUNNING' }));
    const res = await send('PATCH', '/tasks/t1', { status: 'RUNNING' });
    assert.equal(res.status, 200);
    assert.deepEqual(update.mock.calls[0]?.arguments, ['t1', { status: 'RUNNING' }]);
  });

  it('answers with the status of its own errors and of the modules it uses', async () => {
    mock.method(taskService, 'get', async () => Promise.reject(new TaskError(404, 'Task nope not found')));
    const res = await fetch(`${base}/tasks/nope`);
    assert.equal(res.status, 404);
    assert.equal((await res.json()).error, 'Task nope not found');

    mock.method(taskService, 'update', async () => Promise.reject(new CallError(404, 'Call c1 not found')));
    assert.equal((await send('PATCH', '/tasks/t1', { status: 'RUNNING' })).status, 404);
  });

  it('answers 400 for a body that is not JSON, and hides unexpected errors', async () => {
    const res = await fetch(`${base}/tasks`, { method: 'POST', body: '{oops' });
    assert.equal(res.status, 400);

    mock.method(console, 'error', () => {});
    mock.method(taskService, 'list', async () => Promise.reject(new Error('connection refused')));
    const failed = await fetch(`${base}/tasks`);
    assert.equal(failed.status, 500);
    assert.equal((await failed.json()).error, 'Internal server error');
  });

  it('leaves other routes to the caller', async () => {
    await fetch(`${base}/calls`);
    assert.equal(handled, false);
  });
});
