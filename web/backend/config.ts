// Settings from the environment (.env locally, the container's environment in Docker).

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Environment variable ${name} is not set (see .env.example)`);
  return value;
}

export const config = {
  port: Number(required('PORT')),
  dataProviderUrl: required('DATA_PROVIDER_URL'),
  // There is no login yet: every visitor acts as this user.
  currentUserEmail: required('CURRENT_USER_EMAIL'),
};
