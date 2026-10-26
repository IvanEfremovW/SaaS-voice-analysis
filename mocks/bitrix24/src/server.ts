// Mock of the Bitrix24 REST API: the part needed to download call recordings.
//
//   1. voximplant.statistic.get  — list of calls; RECORD_FILE_ID points to the recording
//   2. disk.file.get?id=<RECORD_FILE_ID>  — recording's file info with DOWNLOAD_URL
//   3. download.json?token=...  — the recording itself (what DOWNLOAD_URL points to)
//
// Bitrix24 URLs are /rest/<method> (OAuth app) or /rest/<user_id>/<webhook_code>/<method> (incoming
// webhook), with an optional ".json" suffix. Both forms are accepted; credentials are not checked.

import http from 'node:http';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { diskFileGet } from '#src/disk.file.get/method.ts';
import { restDownloadJson } from '#src/rest.download.json/method.ts';
import { readParams } from '#src/utils/params.ts';
import { sendError } from '#src/utils/response.ts';
import { ApiError } from '#src/utils/types.ts';
import type { MethodHandler } from '#src/utils/types.ts';
import { voximplantStatisticGet } from '#src/voximplant.statistic.get/method.ts';

// Default is in .env.defaults (loaded by `npm start`); a PORT already set in the environment,
// e.g. by docker compose, wins.
const PORT = Number(process.env.PORT);
if (!PORT) throw new Error('PORT is not set: run with --env-file=.env.defaults or set the PORT environment variable');

const METHODS: Record<string, MethodHandler> = {
  'voximplant.statistic.get': voximplantStatisticGet,
  'disk.file.get': diskFileGet,
  'download': restDownloadJson,
};

/**
 * Return the method name (last part of the 'URL path'). Ignores the ".json" at the end.
 * 
 * @example
 * console.log(methodName("/rest/disk.file.get.json")) // "disk.file.get"
 * console.log(methodName("/rest/1/abc123/disk.file.get")) // "disk.file.get"
 */
function methodName(pathname: string): string | null {
  const match = /^\/rest\/(?:\d+\/[^/]+\/)?([^/]+?)(?:\.json)?\/?$/.exec(pathname);
  return match?.[1]?.toLowerCase() ?? null;
}

async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const startedAtMs = Date.now();
  const url = new URL(req.url ?? '/', 'http://localhost');
  const name = methodName(url.pathname);
  const method = name === null ? undefined : METHODS[name];
  if (!method) throw new ApiError(404, 'ERROR_METHOD_NOT_FOUND', 'Method not found!');

  await method({
    req,
    res,
    params: await readParams(req, url),
    baseUrl: `http://${req.headers.host}`,
    startedAtMs,
  });
}

const server = http.createServer((req, res) => {
  res.on('finish', () => console.log(`${req.method} ${req.url} -> ${res.statusCode}`));
  handle(req, res).catch((err: unknown) => {
    if (err instanceof ApiError) {
      sendError(res, err.status, err.code, err.message);
    } else {
      console.error(err);
      sendError(res, 500, 'INTERNAL_SERVER_ERROR', 'Internal server error');
    }
  });
});

server.listen(PORT, () => console.log(`Bitrix24 mock listening on http://localhost:${PORT}`));
