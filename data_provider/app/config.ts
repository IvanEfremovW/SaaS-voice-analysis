// Settings from the environment (.env locally, the container's environment in Docker).

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Environment variable ${name} is not set (see .env.example)`);
  return value;
}

export const config = {
  port: Number(required('PORT')),
  databaseUrl: required('DATABASE_URL'),
  maxFileSizeBytes: Number(required('MAX_FILE_SIZE_MB')) * 1024 * 1024,
  s3: {
    endpoint: required('S3_ENDPOINT'),
    region: required('S3_REGION'),
    accessKey: required('S3_ACCESS_KEY'),
    secretKey: required('S3_SECRET_KEY'),
    bucket: required('S3_BUCKET'),
  },
};
