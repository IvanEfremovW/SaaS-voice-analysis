import http from 'node:http';
import path from 'node:path';
import { config } from '#backend/config.ts';
import { createFrontendHandler } from '#backend/infrastructure/frontend.ts';
import { sendJson } from '#backend/infrastructure/http.ts';
import { handleCallRequest } from '#backend/modules/call/api.ts';
import { handleUserRequest } from '#backend/modules/user/api.ts';

// Where "npm run build" puts the frontend.
const serveFrontend = createFrontendHandler(path.join(import.meta.dirname, '../frontend/dist'));

http
  .createServer(async (req, res) => {
    const { pathname } = new URL(req.url ?? '/', 'http://localhost');
    if (pathname !== '/api' && !pathname.startsWith('/api/')) return serveFrontend(req, res);

    if (await handleCallRequest(req, res)) return;
    if (await handleUserRequest(req, res)) return;
    sendJson(res, 404, { error: `No route for ${req.method} ${pathname}` });
  })
  .listen(config.port, () => console.log(`web listening on port ${config.port}`));
