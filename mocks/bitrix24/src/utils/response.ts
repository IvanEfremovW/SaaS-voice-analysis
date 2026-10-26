// JSON responses in the Bitrix24 envelope.

import type { ServerResponse } from 'node:http';
import { formatDate } from './time.ts';

export function sendJson(res: ServerResponse, status: number, body: object): void {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}

export function sendError(res: ServerResponse, status: number, code: string, description: string): void {
  sendJson(res, status, { error: code, error_description: description });
}

/** The "time" block every Bitrix24 REST response carries. */
export function timeInfo(startedAtMs: number): object {
  const finishedAtMs = Date.now();
  return {
    start: startedAtMs / 1000,
    finish: finishedAtMs / 1000,
    duration: (finishedAtMs - startedAtMs) / 1000,
    processing: 0,
    date_start: formatDate(startedAtMs),
    date_finish: formatDate(finishedAtMs),
    operating_reset_at: Math.floor(startedAtMs / 1000) + 600,
    operating: 0,
  };
}
