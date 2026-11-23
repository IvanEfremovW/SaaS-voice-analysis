// POST   /calls?userId=&clientPhone=&direction=&startedAt=&durationSec=&name=   body: the recording -> 201 { call }
// GET    /calls?userId=&status=&from=&to=                    -> { calls }  (newest first)
// GET    /calls/:id                                          -> { call }
// PATCH  /calls/:id   { userId?, clientPhone?, direction?, startedAt?, durationSec? } -> { call }
// GET    /calls/:id/recording                                -> the recording
// PUT    /calls/:id/recording?name=   body: the new recording -> { call }  (transcription removed, status UPLOADED)
// PATCH  /calls/:id/status   { value, error? }               -> { status }
// DELETE /calls/:id                                          -> 204 (with its transcription, status and recording)
//
// Query values must be URL-encoded, e.g. "+7..." as "%2B7...", or "+" turns into a space.

import type { IncomingMessage, ServerResponse } from 'node:http';
import { config } from '#app/config.ts';
import { FileError } from '#app/modules/data/file/entity.ts';
import { StatusError } from '#app/modules/data/status/entity.ts';
import type { CallStatus } from '#app/modules/data/status/entity.ts';
import { TranscriptionError } from '#app/modules/data/transcription/entity.ts';
import { CallError } from './entity.ts';
import type { CallDirection, CallFilter } from './entity.ts';
import { callService } from './service.ts';

type Route = {
  method: string;
  pattern: RegExp;
  handler: (req: IncomingMessage, res: ServerResponse, url: URL, id: string) => Promise<void>;
};

const routes: Route[] = [
  {
    method: 'POST',
    pattern: /^\/calls$/,
    handler: async (req, res, url) => {
      const q = url.searchParams;
      const call = await callService.create({
        userId: q.get('userId') ?? '',
        clientPhone: q.get('clientPhone') ?? '',
        direction: q.get('direction') as CallDirection,
        startedAt: q.get('startedAt') ?? '',
        durationSec: Number(q.get('durationSec') ?? NaN),
        recording: { name: q.get('name') ?? '', data: await readBody(req) },
      });
      sendJson(res, 201, { call });
    },
  },
  {
    method: 'GET',
    pattern: /^\/calls$/,
    handler: async (_, res, url) => {
      const filter: CallFilter = {};
      for (const key of ['userId', 'from', 'to'] as const) {
        const value = url.searchParams.get(key);
        if (value) filter[key] = value;
      }
      const status = url.searchParams.get('status');
      if (status) filter.status = status as CallStatus;
      sendJson(res, 200, { calls: await callService.list(filter) });
    },
  },
  {
    method: 'GET',
    pattern: /^\/calls\/([^/]+)$/,
    handler: async (_, res, __, id) => sendJson(res, 200, { call: await callService.get(id) }),
  },
  {
    method: 'PATCH',
    pattern: /^\/calls\/([^/]+)$/,
    handler: async (req, res, _, id) => sendJson(res, 200, { call: await callService.update(id, await readJson(req)) }),
  },
  {
    method: 'GET',
    pattern: /^\/calls\/([^/]+)\/recording$/,
    handler: async (_, res, __, id) => {
      const { file, data } = await callService.downloadRecording(id);
      res.writeHead(200, {
        'Content-Type': file.contentType,
        'Content-Length': data.length,
        'Content-Disposition': `attachment; filename="${file.name.replace(/[^\x20-\x7e]|"/g, '_')}"; filename*=UTF-8''${encodeURIComponent(file.name)}`,
      });
      res.end(data);
    },
  },
  {
    method: 'PUT',
    pattern: /^\/calls\/([^/]+)\/recording$/,
    handler: async (req, res, url, id) => {
      const recording = { name: url.searchParams.get('name') ?? '', data: await readBody(req) };
      sendJson(res, 200, { call: await callService.replaceRecording(id, recording) });
    },
  },
  {
    method: 'PATCH',
    pattern: /^\/calls\/([^/]+)\/status$/,
    handler: async (req, res, _, id) => sendJson(res, 200, { status: await callService.updateStatus(id, await readJson(req)) }),
  },
  {
    method: 'DELETE',
    pattern: /^\/calls\/([^/]+)$/,
    handler: async (_, res, __, id) => {
      await callService.delete(id);
      res.writeHead(204).end();
    },
  },
];

// The call service also passes on errors of the modules it uses.
const KNOWN_ERRORS = [CallError, FileError, StatusError, TranscriptionError];

/** Answers the request and returns true if it is a call route, otherwise returns false. */
export async function handleCallRequest(req: IncomingMessage, res: ServerResponse): Promise<boolean> {
  const url = new URL(req.url ?? '/', 'http://localhost');
  for (const route of routes) {
    const match = route.pattern.exec(url.pathname);
    if (!match || route.method !== req.method) continue;
    try {
      await route.handler(req, res, url, decodeURIComponent(match[1] ?? ''));
    } catch (err) {
      const known = KNOWN_ERRORS.some((E) => err instanceof E);
      const status = known ? (err as CallError).status : 500;
      if (!known) console.error(err);
      sendJson(res, status, { error: known ? (err as Error).message : 'Internal server error' });
    }
    return true;
  }
  return false;
}

/** Reads the whole body, refusing it as soon as it grows over the file size limit. */
async function readBody(req: IncomingMessage): Promise<Buffer> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    if (size > config.maxFileSizeBytes) throw new FileError(413, `The file is larger than ${config.maxFileSizeBytes} bytes`);
    chunks.push(chunk as Buffer);
  }
  return Buffer.concat(chunks);
}

async function readJson(req: IncomingMessage) {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw new CallError(400, 'Body must be valid JSON');
  }
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}
