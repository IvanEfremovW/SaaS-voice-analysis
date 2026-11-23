// POST   /statuses       { value? }          -> 201 { status }   (UPLOADED if no value)
// GET    /statuses?value=<value>            -> { statuses }     (latest change first)
// GET    /statuses/:id                      -> { status }
// PATCH  /statuses/:id   { value, error? }  -> { status }       (error required for FAILED)
// DELETE /statuses/:id                      -> 204 (409 if it belongs to a call)

import type { IncomingMessage, ServerResponse } from 'node:http';
import { StatusError } from './entity.ts';
import type { CallStatus } from './entity.ts';
import { statusService } from './service.ts';

type Route = {
  method: string;
  pattern: RegExp;
  handler: (req: IncomingMessage, res: ServerResponse, url: URL, id: string) => Promise<void>;
};

const routes: Route[] = [
  {
    method: 'POST',
    pattern: /^\/statuses$/,
    handler: async (req, res) => {
      const body = (await readJson(req)) ?? {};
      sendJson(res, 201, { status: await statusService.create(body.value) });
    },
  },
  {
    method: 'GET',
    pattern: /^\/statuses$/,
    handler: async (_, res, url) => {
      const value = (url.searchParams.get('value') ?? undefined) as CallStatus | undefined;
      sendJson(res, 200, { statuses: await statusService.list(value) });
    },
  },
  {
    method: 'GET',
    pattern: /^\/statuses\/([^/]+)$/,
    handler: async (_, res, __, id) => sendJson(res, 200, { status: await statusService.get(id) }),
  },
  {
    method: 'PATCH',
    pattern: /^\/statuses\/([^/]+)$/,
    handler: async (req, res, _, id) => sendJson(res, 200, { status: await statusService.update(id, await readJson(req)) }),
  },
  {
    method: 'DELETE',
    pattern: /^\/statuses\/([^/]+)$/,
    handler: async (_, res, __, id) => {
      await statusService.delete(id);
      res.writeHead(204).end();
    },
  },
];

/** Answers the request and returns true if it is a status route, otherwise returns false. */
export async function handleStatusRequest(req: IncomingMessage, res: ServerResponse): Promise<boolean> {
  const url = new URL(req.url ?? '/', 'http://localhost');
  for (const route of routes) {
    const match = route.pattern.exec(url.pathname);
    if (!match || route.method !== req.method) continue;
    try {
      await route.handler(req, res, url, decodeURIComponent(match[1] ?? ''));
    } catch (err) {
      const status = err instanceof StatusError ? err.status : 500;
      if (status === 500) console.error(err);
      sendJson(res, status, { error: status === 500 ? 'Internal server error' : (err as Error).message });
    }
    return true;
  }
  return false;
}

/** The parsed JSON body, or null for an empty body. */
async function readJson(req: IncomingMessage) {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  const text = Buffer.concat(chunks).toString('utf8').trim();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    throw new StatusError(400, 'Body must be valid JSON');
  }
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}
