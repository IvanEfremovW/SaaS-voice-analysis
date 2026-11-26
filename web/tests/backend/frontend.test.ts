import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { after, before, describe, it } from 'node:test';
import { createFrontendHandler } from '#backend/infrastructure/frontend.ts';

let base: string;
let server: http.Server;
let dir: string;

before(async () => {
  dir = await mkdtemp(path.join(os.tmpdir(), 'web-dist-'));
  await mkdir(path.join(dir, 'dist', 'assets'), { recursive: true });
  await writeFile(path.join(dir, 'dist', 'index.html'), '<div id="root"></div>');
  await writeFile(path.join(dir, 'dist', 'assets', 'main-abc123.js'), 'console.log(1)');
  await writeFile(path.join(dir, 'secret.txt'), 'secret');

  server = http.createServer(createFrontendHandler(path.join(dir, 'dist')));
  await new Promise<void>((resolve) => server.listen(0, resolve));
  base = `http://localhost:${(server.address() as AddressInfo).port}`;
});
after(async () => {
  server.close();
  await rm(dir, { recursive: true });
});

describe('frontend handler', () => {
  it('sends index.html for any page path, so React Router can pick the page', async () => {
    for (const page of ['/', '/calls', '/calls/c1']) {
      const res = await fetch(base + page);
      assert.equal(res.status, 200, page);
      assert.equal(res.headers.get('content-type'), 'text/html; charset=utf-8');
      assert.equal(res.headers.get('cache-control'), 'no-cache');
      assert.equal(await res.text(), '<div id="root"></div>');
    }
  });

  it('sends built files with their type, cached for good', async () => {
    const res = await fetch(`${base}/assets/main-abc123.js`);
    assert.equal(res.headers.get('content-type'), 'text/javascript; charset=utf-8');
    assert.match(res.headers.get('cache-control') ?? '', /immutable/);
    assert.equal(await res.text(), 'console.log(1)');
  });

  it('answers 404 for a missing file and for paths outside the folder', async () => {
    assert.equal((await fetch(`${base}/assets/missing.js`)).status, 404);
    assert.equal((await fetch(`${base}/..%2fsecret.txt`)).status, 404);
    assert.equal((await fetch(`${base}/%E0%A4%A`)).status, 404);
  });
});
