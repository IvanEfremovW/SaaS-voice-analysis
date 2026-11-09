import http from 'node:http';
import { config } from '#app/config.ts';
import { handleCallRequest } from '#app/modules/call/api.ts';

http
  .createServer(async (req, res) => {
    if (await handleCallRequest(req, res)) return;
    res.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({ error: `No route for ${req.method} ${req.url}` }));
  })
  .listen(config.port, () => console.log(`data_provider listening on port ${config.port}`));
