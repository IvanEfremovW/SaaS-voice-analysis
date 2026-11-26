import { readFile, stat } from 'node:fs/promises';
import type { IncomingMessage, ServerResponse } from 'node:http';
import path from 'node:path';

const CONTENT_TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
};

/**
 * Serves the built frontend from `dir`: its files as they are, and index.html for any other path,
 * because which page to draw for a URL is decided in the browser by React Router.
 */
export function createFrontendHandler(dir: string) {
  const root = path.resolve(dir) + path.sep;

  return async (req: IncomingMessage, res: ServerResponse): Promise<void> => {
    const { pathname } = new URL(req.url ?? '/', 'http://localhost');
    let file = '';
    try {
      file = path.join(root, decodeURIComponent(pathname));
    } catch {} // malformed %-encoding: answered as not found below
    // Also stops paths like /..%2f..%2fsecret from reading files outside the folder.
    if (!file.startsWith(root)) return notFound(res);

    if (await isFile(file)) return send(res, file);
    // A missing file (the path has an extension) is a real 404; any other path is a page of the app.
    if (path.extname(pathname)) return notFound(res);

    const index = path.join(root, 'index.html');
    if (!(await isFile(index))) return notFound(res, 'The frontend is not built: run "npm run build", or use the Vite dev server');
    return send(res, index);
  };
}

async function send(res: ServerResponse, file: string): Promise<void> {
  const data = await readFile(file);
  res.writeHead(200, {
    'Content-Type': CONTENT_TYPES[path.extname(file)] ?? 'application/octet-stream',
    // Built files in assets/ have a content hash in their name, so they never change and can be cached forever.
    // index.html keeps its name, so the browser must check it every time to pick up a new build.
    'Cache-Control': file.includes(`${path.sep}assets${path.sep}`) ? 'public, max-age=31536000, immutable' : 'no-cache',
  });
  res.end(data);
}

function notFound(res: ServerResponse, message = 'Not found'): void {
  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end(message);
}

async function isFile(file: string): Promise<boolean> {
  return (await stat(file).catch(() => null))?.isFile() ?? false;
}
