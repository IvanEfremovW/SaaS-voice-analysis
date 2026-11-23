// POST   /transcriptions  { callId, fileId }  -> 201 { transcription }  (fileId: an uploaded "transcription" file)
// GET    /transcriptions?callId=<call id>     -> { transcriptions }
// GET    /transcriptions/:id                  -> { transcription }
// GET    /transcriptions/:id/content          -> the transcription file (JSON)
// DELETE /transcriptions/:id                  -> 204, deletes its file too

import type { IncomingMessage, ServerResponse } from 'node:http';
import { TranscriptionError } from './entity.ts';
import { transcriptionService } from './service.ts';

type Route = {
  method: string;
  pattern: RegExp;
  handler: (req: IncomingMessage, res: ServerResponse, url: URL, id: string) => Promise<void>;
};

const routes: Route[] = [
  {
    method: 'POST',
    pattern: /^\/transcriptions$/,
    handler: async (req, res) => {
      sendJson(res, 201, { transcription: await transcriptionService.create(await readJson(req)) });
    },
  },
  {
    method: 'GET',
    pattern: /^\/transcriptions$/,
    handler: async (_, res, url) => {
      const callId = url.searchParams.get('callId') ?? undefined;
      sendJson(res, 200, { transcriptions: await transcriptionService.list(callId) });
    },
  },
  {
    method: 'GET',
    pattern: /^\/transcriptions\/([^/]+)$/,
    handler: async (_, res, __, id) => sendJson(res, 200, { transcription: await transcriptionService.get(id) }),
  },
  {
    method: 'GET',
    pattern: /^\/transcriptions\/([^/]+)\/content$/,
    handler: async (_, res, __, id) => {
      const { file, data } = await transcriptionService.content(id);
      res.writeHead(200, { 'Content-Type': file.contentType, 'Content-Length': data.length });
      res.end(data);
    },
  },
  {
    method: 'DELETE',
    pattern: /^\/transcriptions\/([^/]+)$/,
    handler: async (_, res, __, id) => {
      await transcriptionService.delete(id);
      res.writeHead(204).end();
    },
  },
];

/** Answers the request and returns true if it is a transcription route, otherwise returns false. */
export async function handleTranscriptionRequest(req: IncomingMessage, res: ServerResponse): Promise<boolean> {
  const url = new URL(req.url ?? '/', 'http://localhost');
  for (const route of routes) {
    const match = route.pattern.exec(url.pathname);
    if (!match || route.method !== req.method) continue;
    try {
      await route.handler(req, res, url, decodeURIComponent(match[1] ?? ''));
    } catch (err) {
      const status = err instanceof TranscriptionError ? err.status : 500;
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
    throw new TranscriptionError(400, 'Body must be valid JSON');
  }
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}
