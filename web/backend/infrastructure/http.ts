import type { IncomingMessage, ServerResponse } from 'node:http';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import type { ReadableStream as WebReadableStream } from 'node:stream/web';

/** An error with the HTTP status the API answers with. */
export class HttpError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export type Route = {
  method: string;
  pattern: RegExp;
  /** `id` is the first group of the pattern, if it has one. */
  handler: (req: IncomingMessage, res: ServerResponse, url: URL, id: string) => Promise<void>;
};

/**
 * Answers the request with the first matching route and returns true, or returns false if none matches.
 * An HttpError is answered with its status; anything else is logged and answered with 500.
 */
export async function handleRoutes(routes: Route[], req: IncomingMessage, res: ServerResponse): Promise<boolean> {
  const url = new URL(req.url ?? '/', 'http://localhost');
  for (const route of routes) {
    const match = route.pattern.exec(url.pathname);
    if (!match || route.method !== req.method) continue;
    try {
      await route.handler(req, res, url, decodeURIComponent(match[1] ?? ''));
    } catch (err) {
      if (!(err instanceof HttpError)) console.error(err);
      if (res.headersSent) res.destroy();
      else if (err instanceof HttpError) sendJson(res, err.status, { error: err.message });
      else sendJson(res, 500, { error: 'Internal server error' });
    }
    return true;
  }
  return false;
}

export function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}

/** Streams a file answer of another service (e.g. a recording from data_provider) to the browser. */
export async function sendFile(res: ServerResponse, file: Response): Promise<void> {
  const headers: Record<string, string> = {};
  for (const name of ['content-type', 'content-length', 'content-disposition']) {
    const value = file.headers.get(name);
    if (value) headers[name] = value;
  }
  res.writeHead(200, headers);
  // The cast only settles a mismatch between the DOM and Node typings of the same stream.
  if (file.body) await pipeline(Readable.fromWeb(file.body as WebReadableStream), res);
  else res.end();
}
