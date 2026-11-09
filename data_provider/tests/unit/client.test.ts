import assert from 'node:assert/strict';
import { afterEach, describe, it, mock } from 'node:test';
import { BitrixCallClient } from '#app/modules/call/client.ts';
import { CallError } from '#app/modules/call/entity.ts';

const WEBHOOK = 'http://bitrix.test/rest/1/hook';

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function mockFetch(handler: (url: URL) => Response | Promise<Response>) {
  return mock.method(globalThis, 'fetch', async (input: string | URL | Request) => handler(new URL(String(input))));
}

const isCallError = (status: number) => (err: unknown) => err instanceof CallError && err.status === status;

afterEach(() => mock.restoreAll());

describe('BitrixCallClient', () => {
  it('collects every page and passes the period filter', async () => {
    const urls: URL[] = [];
    mockFetch((url) => {
      urls.push(url);
      return url.searchParams.get('start') === '0'
        ? json({ result: [{ CALL_ID: 'a' }], next: 50, total: 2 })
        : json({ result: [{ CALL_ID: 'b' }], total: 2 });
    });

    const calls = await new BitrixCallClient(WEBHOOK).listCalls({ from: '2026-10-01', to: '2026-10-15' });

    assert.deepEqual(calls.map((c) => c.CALL_ID), ['a', 'b']);
    assert.equal(urls[0]?.pathname, '/rest/1/hook/voximplant.statistic.get');
    assert.equal(urls[0]?.searchParams.get('FILTER[>=CALL_START_DATE]'), '2026-10-01');
    assert.equal(urls[0]?.searchParams.get('FILTER[<CALL_START_DATE]'), '2026-10-15');
    assert.equal(urls[1]?.searchParams.get('start'), '50');
  });

  it('turns a Bitrix24 error into a CallError with the same status', async () => {
    mockFetch(() => json({ error: 'ERROR_NOT_FOUND', error_description: 'Could not find entity' }, 404));
    await assert.rejects(new BitrixCallClient(WEBHOOK).getFile('1'), isCallError(404));
  });

  it('reports an unreachable Bitrix24 as 502', async () => {
    mockFetch(() => {
      throw new TypeError('fetch failed');
    });
    await assert.rejects(new BitrixCallClient(WEBHOOK).listCalls({}), isCallError(502));
  });

  it('downloads the file bytes with their content type', async () => {
    mockFetch(() => new Response(Buffer.from('RIFF'), { headers: { 'Content-Type': 'audio/wav' } }));
    const file = await new BitrixCallClient(WEBHOOK).download('http://bitrix.test/download');
    assert.equal(file.data.toString(), 'RIFF');
    assert.equal(file.contentType, 'audio/wav');
  });

  it('reports a failed download with its status', async () => {
    mockFetch(() => new Response('gone', { status: 404 }));
    await assert.rejects(new BitrixCallClient(WEBHOOK).download('http://bitrix.test/download'), isCallError(404));
  });
});
