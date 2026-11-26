// GET  /api/calls?userId=&direction=&from=&to=&sort=&order=  -> { calls }
// GET  /api/calls/:id                  -> { call }  (with its recording and transcription)
// GET  /api/calls/:id/recording        -> the recording file
// GET  /api/calls/:id/transcription    -> the transcription file
// POST /api/calls/:id/transcription    -> 204  (deletes the old transcription and asks for a new one)

import type { IncomingMessage, ServerResponse } from 'node:http';
import { handleRoutes, sendFile, sendJson } from '#backend/infrastructure/http.ts';
import type { Route } from '#backend/infrastructure/http.ts';
import type { CallQuery } from './entity.ts';
import { callService } from './service.ts';

const routes: Route[] = [
  {
    method: 'GET',
    pattern: /^\/api\/calls$/,
    handler: async (_, res, url) => {
      // An empty field ("?userId=", an unused filter of a form) counts as not given.
      const query = Object.fromEntries([...url.searchParams].filter(([, value]) => value)) as CallQuery;
      sendJson(res, 200, { calls: await callService.list(query) });
    },
  },
  {
    method: 'GET',
    pattern: /^\/api\/calls\/([^/]+)$/,
    handler: async (_, res, __, id) => sendJson(res, 200, { call: await callService.get(id) }),
  },
  {
    method: 'GET',
    pattern: /^\/api\/calls\/([^/]+)\/recording$/,
    handler: async (_, res, __, id) => sendFile(res, await callService.downloadRecording(id)),
  },
  {
    method: 'GET',
    pattern: /^\/api\/calls\/([^/]+)\/transcription$/,
    handler: async (_, res, __, id) => sendFile(res, await callService.downloadTranscription(id)),
  },
  {
    method: 'POST',
    pattern: /^\/api\/calls\/([^/]+)\/transcription$/,
    handler: async (_, res, __, id) => {
      await callService.requestTranscription(id);
      res.writeHead(204).end();
    },
  },
];

/** Answers the request and returns true if it is a call route, otherwise returns false. */
export function handleCallRequest(req: IncomingMessage, res: ServerResponse): Promise<boolean> {
  return handleRoutes(routes, req, res);
}
