import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import type { S3Client } from '@aws-sdk/client-s3';
import { S3Storage } from '#app/infrastructure/s3.ts';

type Sent = { command: string; input: Record<string, unknown> };

/** S3 client fake: records the commands and answers with `respond`. */
function fakeClient(respond: (command: string) => unknown = () => ({})) {
  const sent: Sent[] = [];
  const client = {
    send: async (cmd: { constructor: { name: string }; input: Record<string, unknown> }) => {
      sent.push({ command: cmd.constructor.name, input: cmd.input });
      return respond(cmd.constructor.name);
    },
  };
  return { client: client as unknown as S3Client, sent };
}

const notFound = () => Object.assign(new Error('Not Found'), { name: 'NotFound', $metadata: { httpStatusCode: 404 } });

describe('S3Storage', () => {
  it('uploads and returns the s3:// URI of the file', async () => {
    const { client, sent } = fakeClient();
    const uri = await new S3Storage(client, 'calls').upload('2026/a b.wav', Buffer.from('RIFF'), 'audio/wav');

    assert.equal(uri, 's3://calls/2026/a%20b.wav');
    assert.equal(sent[0]?.command, 'PutObjectCommand');
    assert.deepEqual({ ...sent[0]?.input, Body: undefined }, {
      Bucket: 'calls',
      Key: '2026/a b.wav',
      Body: undefined,
      ContentType: 'audio/wav',
    });
  });

  it('downloads a file by its URI', async () => {
    const { client, sent } = fakeClient(() => ({ Body: { transformToByteArray: async () => Buffer.from('RIFF') } }));
    const data = await new S3Storage(client, 'calls').download('s3://calls/2026/a%20b.wav');

    assert.equal(data.toString(), 'RIFF');
    assert.equal(sent[0]?.input.Key, '2026/a b.wav');
  });

  it('rejects a URI of another bucket', async () => {
    const { client } = fakeClient();
    await assert.rejects(new S3Storage(client, 'calls').download('s3://other/x.wav'), /not a file of bucket "calls"/);
  });

  it('exists() is false for a missing file', async () => {
    const { client } = fakeClient(() => {
      throw notFound();
    });
    assert.equal(await new S3Storage(client, 'calls').exists('s3://calls/x.wav'), false);
  });

  it('ensureBucket() creates the bucket only when it is missing', async () => {
    const missing = fakeClient((command) => {
      if (command === 'HeadBucketCommand') throw notFound();
      return {};
    });
    await new S3Storage(missing.client, 'calls').ensureBucket();
    assert.deepEqual(missing.sent.map((s) => s.command), ['HeadBucketCommand', 'CreateBucketCommand']);

    const present = fakeClient();
    await new S3Storage(present.client, 'calls').ensureBucket();
    assert.deepEqual(present.sent.map((s) => s.command), ['HeadBucketCommand']);
  });
});
