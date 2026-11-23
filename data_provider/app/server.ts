import http from 'node:http';
import { config } from '#app/config.ts';
import { s3Storage } from '#app/infrastructure/s3.ts';
import { handleCallRequest } from '#app/modules/data/call/api.ts';
import { handleFileRequest } from '#app/modules/data/file/api.ts';
import { handleStatusRequest } from '#app/modules/data/status/api.ts';
import { handleUserRequest } from '#app/modules/data/user/api.ts';

await s3Storage.ensureBucket();

http
  .createServer(async (req, res) => {
    if (await handleUserRequest(req, res)) return;
    if (await handleFileRequest(req, res)) return;
    if (await handleStatusRequest(req, res)) return;
    if (await handleCallRequest(req, res)) return;
    res.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({ error: `No route for ${req.method} ${req.url}` }));
  })
  .listen(config.port, () => console.log(`data_provider listening on port ${config.port}`));
