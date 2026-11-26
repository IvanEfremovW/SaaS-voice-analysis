// POST   /users                  { name, email, password, role? } -> 201 { user }
// GET    /users                                                  -> { users }
// GET    /users/:id                                              -> { user }
// PATCH  /users/:id              { name?, email?, role? }        -> { user }
// PUT    /users/:id/password     { password }                    -> 204
// POST   /users/check-password   { email, password }             -> { user }  (401 if either is wrong)
// DELETE /users/:id                                              -> 204 (409 if the user still has calls)
//
// Passwords are 8-128 characters and stored only as hashes; no answer ever contains a password or hash.
// This service doesn't know who is logged in: the caller (the web backend) lets only admins change passwords.

import type { IncomingMessage, ServerResponse } from 'node:http';
import { UserError } from './entity.ts';
import { userService } from './service.ts';

type Route = {
  method: string;
  pattern: RegExp;
  handler: (req: IncomingMessage, res: ServerResponse, id: string) => Promise<void>;
};

const routes: Route[] = [
  {
    method: 'POST',
    pattern: /^\/users$/,
    handler: async (req, res) => sendJson(res, 201, { user: await userService.create(await readJson(req)) }),
  },
  {
    method: 'GET',
    pattern: /^\/users$/,
    handler: async (_, res) => sendJson(res, 200, { users: await userService.list() }),
  },
  {
    method: 'GET',
    pattern: /^\/users\/([^/]+)$/,
    handler: async (_, res, id) => sendJson(res, 200, { user: await userService.get(id) }),
  },
  {
    method: 'PATCH',
    pattern: /^\/users\/([^/]+)$/,
    handler: async (req, res, id) => sendJson(res, 200, { user: await userService.update(id, await readJson(req)) }),
  },
  {
    method: 'PUT',
    pattern: /^\/users\/([^/]+)\/password$/,
    handler: async (req, res, id) => {
      await userService.setPassword(id, await readJson(req));
      res.writeHead(204).end();
    },
  },
  {
    method: 'POST',
    pattern: /^\/users\/check-password$/,
    handler: async (req, res) => sendJson(res, 200, { user: await userService.checkPassword(await readJson(req)) }),
  },
  {
    method: 'DELETE',
    pattern: /^\/users\/([^/]+)$/,
    handler: async (_, res, id) => {
      await userService.delete(id);
      res.writeHead(204).end();
    },
  },
];

/** Answers the request and returns true if it is a user route, otherwise returns false. */
export async function handleUserRequest(req: IncomingMessage, res: ServerResponse): Promise<boolean> {
  const url = new URL(req.url ?? '/', 'http://localhost');
  for (const route of routes) {
    const match = route.pattern.exec(url.pathname);
    if (!match || route.method !== req.method) continue;
    try {
      await route.handler(req, res, decodeURIComponent(match[1] ?? ''));
    } catch (err) {
      const status = err instanceof UserError ? err.status : 500;
      if (status === 500) console.error(err);
      sendJson(res, status, { error: status === 500 ? 'Internal server error' : (err as Error).message });
    }
    return true;
  }
  return false;
}

async function readJson(req: IncomingMessage) {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw new UserError(400, 'Body must be valid JSON');
  }
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}
