// GET  /calls?from=<ISO>&to=<ISO>             -> { calls: Call[] }
// GET  /calls/recordings/:recordingId          -> the recording file
// POST /calls/recordings/:recordingId/download -> 202 { download: Download }, saves the file to disk
// GET  /calls/downloads/:downloadId            -> { download: Download }

import type { IncomingMessage, ServerResponse } from 'node:http';
import { CallError } from './entity.ts';
import type { CallFilter } from './entity.ts';
import { callService } from './service.ts';

type Route = {
  method: string;
  pattern: RegExp;
  handler: (res: ServerResponse, param: string, url: URL) => void | Promise<void>;
};

const routes: Route[] = [
  {
    method: 'GET',
    pattern: /^\/calls$/,
    handler: async (res, _, url) => {
      sendJson(res, 200, { calls: await callService.listCalls(parseFilter(url)) });
    },
  },
  {
    method: 'GET',
    pattern: /^\/calls\/recordings\/([^/]+)$/,
    handler: async (res, recordingId) => {
      const recording = await callService.downloadRecording(recordingId);
      res.writeHead(200, {
        'Content-Type': recording.contentType,
        'Content-Disposition': `attachment; filename="${recording.fileName}"`,
      });
      res.end(recording.data);
    },
  },
  {
    method: 'POST',
    pattern: /^\/calls\/recordings\/([^/]+)\/download$/,
    handler: (res, recordingId) => {
      sendJson(res, 202, { download: callService.startDownload(recordingId) });
    },
  },
  {
    method: 'GET',
    pattern: /^\/calls\/downloads\/([^/]+)$/,
    handler: (res, downloadId) => {
      const download = callService.getDownload(downloadId);
      if (!download) throw new CallError(404, `Download ${downloadId} not found`);
      sendJson(res, 200, { download });
    },
  },
];

/** Answers the request and returns true if it is a call route, otherwise returns false. */
export async function handleCallRequest(req: IncomingMessage, res: ServerResponse): Promise<boolean> {
  const url = new URL(req.url ?? '/', 'http://localhost');
  for (const route of routes) {
    const match = route.pattern.exec(url.pathname);
    if (!match || route.method !== req.method) continue;
    try {
      await route.handler(res, decodeURIComponent(match[1] ?? ''), url);
    } catch (err) {
      const status = err instanceof CallError ? err.status : 500;
      sendJson(res, status, { error: err instanceof Error ? err.message : String(err) });
    }
    return true;
  }
  return false;
}

function parseFilter(url: URL): CallFilter {
  const filter: CallFilter = {};
  for (const key of ['from', 'to'] as const) {
    const value = url.searchParams.get(key);
    if (value === null) continue;
    if (Number.isNaN(Date.parse(value))) throw new CallError(400, `"${key}" must be an ISO-8601 date`);
    filter[key] = value;
  }
  return filter;
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}
