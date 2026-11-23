// POST   /files?type=<type>&name=<file name>  body: the file bytes -> 201 { file }
// GET    /files?type=<type>                                     -> { files }
// GET    /files/:id                                             -> { file }
// GET    /files/:id/content                                     -> the file bytes
// DELETE /files/:id                                             -> 204 (409 if a call or transcription uses it)

import type { IncomingMessage, ServerResponse } from 'node:http';
import { config } from '#app/config.ts';
import { FileError } from './entity.ts';
import type { FileType } from './entity.ts';
import { fileService } from './service.ts';

type Route = {
  method: string;
  pattern: RegExp;
  handler: (req: IncomingMessage, res: ServerResponse, url: URL, id: string) => Promise<void>;
};

const routes: Route[] = [
  {
    method: 'POST',
    pattern: /^\/files$/,
    handler: async (req, res, url) => {
      const file = await fileService.upload({
        name: url.searchParams.get('name') ?? '',
        type: url.searchParams.get('type') as FileType,
        data: await readBody(req, config.maxFileSizeBytes),
      });
      sendJson(res, 201, { file });
    },
  },
  {
    method: 'GET',
    pattern: /^\/files$/,
    handler: async (_, res, url) => {
      const type = (url.searchParams.get('type') ?? undefined) as FileType | undefined;
      sendJson(res, 200, { files: await fileService.list(type) });
    },
  },
  {
    method: 'GET',
    pattern: /^\/files\/([^/]+)$/,
    handler: async (_, res, __, id) => sendJson(res, 200, { file: await fileService.get(id) }),
  },
  {
    method: 'GET',
    pattern: /^\/files\/([^/]+)\/content$/,
    handler: async (_, res, __, id) => {
      const { file, data } = await fileService.download(id);
      res.writeHead(200, {
        'Content-Type': file.contentType,
        'Content-Length': data.length,
        // Plain ASCII fallback plus the exact (e.g. Cyrillic) name, RFC 6266
        'Content-Disposition': `attachment; filename="${file.name.replace(/[^\x20-\x7e]|"/g, '_')}"; filename*=UTF-8''${encodeURIComponent(file.name)}`,
      });
      res.end(data);
    },
  },
  {
    method: 'DELETE',
    pattern: /^\/files\/([^/]+)$/,
    handler: async (_, res, __, id) => {
      await fileService.delete(id);
      res.writeHead(204).end();
    },
  },
];

/** Answers the request and returns true if it is a file route, otherwise returns false. */
export async function handleFileRequest(req: IncomingMessage, res: ServerResponse): Promise<boolean> {
  const url = new URL(req.url ?? '/', 'http://localhost');
  for (const route of routes) {
    const match = route.pattern.exec(url.pathname);
    if (!match || route.method !== req.method) continue;
    try {
      await route.handler(req, res, url, decodeURIComponent(match[1] ?? ''));
    } catch (err) {
      const status = err instanceof FileError ? err.status : 500;
      if (status === 500) console.error(err);
      sendJson(res, status, { error: status === 500 ? 'Internal server error' : (err as Error).message });
    }
    return true;
  }
  return false;
}

/** Reads the whole body, refusing it as soon as it grows over the limit. */
async function readBody(req: IncomingMessage, limit: number): Promise<Buffer> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    if (size > limit) throw new FileError(413, `The file is larger than ${limit} bytes`);
    chunks.push(chunk as Buffer);
  }
  return Buffer.concat(chunks);
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}
