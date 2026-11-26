import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import type { DatabaseClient } from '#app/infrastructure/database.ts';
import { UserError } from '#app/modules/data/user/entity.ts';
import { UserRepository } from '#app/modules/data/user/repository.ts';

const row = {
  id: 'u1',
  name: 'Anna',
  email: 'anna@example.com',
  role: 'USER',
  password_hash: 'scrypt$1024$8$1$salt$hash',
  created_at: new Date('2026-11-01T10:00:00Z'),
  updated_at: new Date('2026-11-02T10:00:00Z'),
};

const prismaError = (code: string) => Object.assign(new Error(code), { code });

/** A database client whose user table answers with `user`. */
const fakeDb = (user: Record<string, (...args: unknown[]) => Promise<unknown>>) =>
  ({ user }) as unknown as DatabaseClient;

const isUserError = (status: number) => (err: unknown) => err instanceof UserError && err.status === status;

describe('UserRepository', () => {
  it('maps a row to a User, without the password hash', async () => {
    const repo = new UserRepository(fakeDb({ findUnique: async () => row }));
    assert.deepEqual(await repo.findById('u1'), {
      id: 'u1',
      name: 'Anna',
      email: 'anna@example.com',
      role: 'USER',
      createdAt: '2026-11-01T10:00:00.000Z',
      updatedAt: '2026-11-02T10:00:00.000Z',
    });
  });

  it('saves the password hash into its column', async () => {
    const created: unknown[] = [];
    const repo = new UserRepository(fakeDb({ create: async (args) => (created.push(args), row) }));
    await repo.create({ name: 'Anna', email: 'anna@example.com', passwordHash: row.password_hash });
    assert.deepEqual(created, [{ data: { name: 'Anna', email: 'anna@example.com', password_hash: row.password_hash } }]);
  });

  it('gives the hash only together with its user, looked up by email', async () => {
    const repo = new UserRepository(fakeDb({ findUnique: async () => row }));
    const found = await repo.findWithPasswordHash('anna@example.com');
    assert.equal(found?.passwordHash, row.password_hash);
    assert.equal(found?.user.id, 'u1');
    assert.ok(!('password_hash' in (found?.user ?? {})));
  });

  it('reports a taken email as 409', async () => {
    const repo = new UserRepository(fakeDb({ create: async () => Promise.reject(prismaError('P2002')) }));
    await assert.rejects(repo.create({ name: 'Anna', email: 'anna@example.com', passwordHash: 'x' }), isUserError(409));
  });

  it('returns null / false for a missing user on update and delete', async () => {
    const missing = async () => Promise.reject(prismaError('P2025'));
    const repo = new UserRepository(fakeDb({ update: missing, delete: missing }));
    assert.equal(await repo.update('nope', { name: 'X' }), null);
    assert.equal(await repo.setPasswordHash('nope', 'x'), false);
    assert.equal(await repo.delete('nope'), false);
  });

  it('refuses to delete a user who still has calls', async () => {
    const repo = new UserRepository(fakeDb({ delete: async () => Promise.reject(prismaError('P2003')) }));
    await assert.rejects(repo.delete('u1'), isUserError(409));
  });
});
