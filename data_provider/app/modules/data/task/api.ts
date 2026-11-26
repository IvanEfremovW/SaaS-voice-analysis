// POST  /tasks       { callId, type, metadata? }  -> 201 { task }
// GET   /tasks?callId=&type=&status=             -> { tasks }  (newest first)
// GET   /tasks/:id                               -> { task }
// PATCH /tasks/:id   { status, error? }          -> { task }
//
// type: TRANSCRIPTION or ANALYSIS. status: QUEUED -> RUNNING -> SUCCEEDED or FAILED ("error" required for FAILED).
// A call has at most one unfinished (QUEUED or RUNNING) task; POST answers 409 while it has one.
// POST of a TRANSCRIPTION deletes the call's old transcription and sets the call to UPLOADED;
// an ANALYSIS needs a transcription and sets the call to TRANSCRIBED.
// The call's status follows its task: RUNNING, SUCCEEDED and FAILED of a TRANSCRIPTION move the call to
// TRANSCRIBING, TRANSCRIBED and FAILED; of an ANALYSIS to ANALYZING, ANALYZED and FAILED.
// A TRANSCRIPTION can succeed only once its transcription is saved (POST /transcriptions).

import type { IncomingMessage, ServerResponse } from 'node:http';
import { CallError } from '#app/modules/data/call/entity.ts';
import { StatusError } from '#app/modules/data/status/entity.ts';
import { TranscriptionError } from '#app/modules/data/transcription/entity.ts';
import { TaskError } from './entity.ts';
import type { TaskFilter } from './entity.ts';
import { taskService } from './service.ts';

type Route = {
  method: string;
  pattern: RegExp;
  handler: (req: IncomingMessage, res: ServerResponse, url: URL, id: string) => Promise<void>;
};

const routes: Route[] = [
  {
    method: 'POST',
    pattern: /^\/tasks$/,
    handler: async (req, res) => sendJson(res, 201, { task: await taskService.create(await readJson(req)) }),
  },
  {
    method: 'GET',
    pattern: /^\/tasks$/,
    handler: async (_, res, url) => {
      const filter: Record<string, string> = {};
      for (const key of ['callId', 'type', 'status'] as const) {
        const value = url.searchParams.get(key);
        if (value) filter[key] = value;
      }
      sendJson(res, 200, { tasks: await taskService.list(filter as TaskFilter) });
    },
  },
  {
    method: 'GET',
    pattern: /^\/tasks\/([^/]+)$/,
    handler: async (_, res, __, id) => sendJson(res, 200, { task: await taskService.get(id) }),
  },
  {
    method: 'PATCH',
    pattern: /^\/tasks\/([^/]+)$/,
    handler: async (req, res, _, id) => sendJson(res, 200, { task: await taskService.update(id, await readJson(req)) }),
  },
];

// The task service also passes on errors of the modules it uses.
const KNOWN_ERRORS = [TaskError, CallError, StatusError, TranscriptionError];

/** Answers the request and returns true if it is a task route, otherwise returns false. */
export async function handleTaskRequest(req: IncomingMessage, res: ServerResponse): Promise<boolean> {
  const url = new URL(req.url ?? '/', 'http://localhost');
  for (const route of routes) {
    const match = route.pattern.exec(url.pathname);
    if (!match || route.method !== req.method) continue;
    try {
      await route.handler(req, res, url, decodeURIComponent(match[1] ?? ''));
    } catch (err) {
      const known = KNOWN_ERRORS.some((E) => err instanceof E);
      const status = known ? (err as TaskError).status : 500;
      if (!known) console.error(err);
      sendJson(res, status, { error: known ? (err as Error).message : 'Internal server error' });
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
    throw new TaskError(400, 'Body must be valid JSON');
  }
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}
