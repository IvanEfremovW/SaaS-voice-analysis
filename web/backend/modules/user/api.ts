// GET    /api/me          -> { user }  (the logged-in user)
// GET    /api/users       -> { users }
// DELETE /api/users/:id   -> 204  (admins only; 409 if the user still has calls)

import type { IncomingMessage, ServerResponse } from 'node:http';
import { handleRoutes, sendJson } from '#backend/infrastructure/http.ts';
import type { Route } from '#backend/infrastructure/http.ts';
import { userService } from './service.ts';

const routes: Route[] = [
  {
    method: 'GET',
    pattern: /^\/api\/me$/,
    handler: async (req, res) => sendJson(res, 200, { user: await userService.current(req) }),
  },
  {
    method: 'GET',
    pattern: /^\/api\/users$/,
    handler: async (_, res) => sendJson(res, 200, { users: await userService.list() }),
  },
  {
    method: 'DELETE',
    pattern: /^\/api\/users\/([^/]+)$/,
    handler: async (req, res, _, id) => {
      await userService.delete(await userService.current(req), id);
      res.writeHead(204).end();
    },
  },
];

/** Answers the request and returns true if it is a user route, otherwise returns false. */
export function handleUserRequest(req: IncomingMessage, res: ServerResponse): Promise<boolean> {
  return handleRoutes(routes, req, res);
}
