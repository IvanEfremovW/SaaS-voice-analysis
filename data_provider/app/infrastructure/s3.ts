import {
  CreateBucketCommand,
  DeleteObjectCommand,
  GetObjectCommand,
  HeadBucketCommand,
  HeadObjectCommand,
  PutObjectCommand,
  S3Client,
} from '@aws-sdk/client-s3';
import { config } from '#app/config.ts';

/** Files in one S3 bucket. A file is addressed by its URI "s3://<bucket>/<key>", as stored in file.uri. */
export class S3Storage {
  #client: S3Client;
  #bucket: string;

  constructor(client: S3Client, bucket: string) {
    this.#client = client;
    this.#bucket = bucket;
  }

  async ensureBucket(): Promise<void> {
    try {
      await this.#client.send(new HeadBucketCommand({ Bucket: this.#bucket }));
    } catch (err) {
      if (!isNotFound(err)) throw err;
      await this.#client.send(new CreateBucketCommand({ Bucket: this.#bucket }));
    }
  }

  /** Returns the URI of the uploaded file. */
  async upload(key: string, body: Buffer, contentType: string): Promise<string> {
    await this.#client.send(new PutObjectCommand({ Bucket: this.#bucket, Key: key, Body: body, ContentType: contentType }));
    return `s3://${this.#bucket}/${key.split('/').map(encodeURIComponent).join('/')}`;
  }

  async download(uri: string): Promise<Buffer> {
    const res = await this.#client.send(new GetObjectCommand({ Bucket: this.#bucket, Key: this.#key(uri) }));
    if (!res.Body) throw new Error(`Empty response for ${uri}`);
    return Buffer.from(await res.Body.transformToByteArray());
  }

  async exists(uri: string): Promise<boolean> {
    try {
      await this.#client.send(new HeadObjectCommand({ Bucket: this.#bucket, Key: this.#key(uri) }));
      return true;
    } catch (err) {
      if (isNotFound(err)) return false;
      throw err;
    }
  }

  async delete(uri: string): Promise<void> {
    await this.#client.send(new DeleteObjectCommand({ Bucket: this.#bucket, Key: this.#key(uri) }));
  }

  #key(uri: string): string {
    const url = new URL(uri);
    if (url.protocol !== 's3:' || url.host !== this.#bucket) {
      throw new Error(`"${uri}" is not a file of bucket "${this.#bucket}"`);
    }
    return decodeURIComponent(url.pathname.slice(1));
  }
}

function isNotFound(err: unknown): boolean {
  const status = (err as { $metadata?: { httpStatusCode?: number } }).$metadata?.httpStatusCode;
  return status === 404 || (err instanceof Error && ['NotFound', 'NoSuchKey', 'NoSuchBucket'].includes(err.name));
}

export const s3Storage = new S3Storage(
  new S3Client({
    endpoint: config.s3.endpoint,
    region: config.s3.region,
    credentials: { accessKeyId: config.s3.accessKey, secretAccessKey: config.s3.secretKey },
    // MinIO and most S3-compatible servers expect http://host/<bucket>/<key> rather than http://<bucket>.host/<key>.
    forcePathStyle: true,
  }),
  config.s3.bucket,
);
