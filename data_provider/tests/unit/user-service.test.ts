import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { describe, it } from 'node:test';
import type { DatabaseClient } from '#app/infrastructure/database.ts';
import { UserError } from '#app/modules/data/user/entity.ts';
import type { CreateUserInput, UpdateUserInput, User } from '#app/modules/data/user/entity.ts';
import { PasswordHasher } from '#app/modules/data/user/password.ts';
import { UserRepository } from '#app/modules/data/user/repository.ts';
import { UserService } from '#app/modules/data/user/service.ts';
import type { NewUser, UserWithPasswordHash } from '#app/modules/data/user/types.ts';

class FakeUserRepository extends UserRepository {
  users = new Map<string, User>();
  hashes = new Map<string, string>();
  lastUpdate: UpdateUserInput | undefined;

  constructor() {
    super({} as DatabaseClient);
  }

  override async create({ passwordHash, ...fields }: NewUser): Promise<User> {
    const now = new Date().toISOString();
    const user: User = { id: randomUUID(), role: 'USER', ...fields, createdAt: now, updatedAt: now };
    this.users.set(user.id, user);
    this.hashes.set(user.id, passwordHash);
    return user;
  }

  override async findById(id: string): Promise<User | null> {
    return this.users.get(id) ?? null;
  }

  override async findWithPasswordHash(email: string): Promise<UserWithPasswordHash | null> {
    const user = [...this.users.values()].find((u) => u.email === email);
    return user ? { user, passwordHash: this.hashes.get(user.id)! } : null;
  }

  override async update(id: string, input: UpdateUserInput): Promise<User | null> {
    this.lastUpdate = input;
    const user = this.users.get(id);
    return user ? { ...user, ...input } : null;
  }

  override async setPasswordHash(id: string, passwordHash: string): Promise<boolean> {
    if (!this.users.has(id)) return false;
    this.hashes.set(id, passwordHash);
    return true;
  }

  override async delete(id: string): Promise<boolean> {
    return this.users.delete(id);
  }
}

function setup() {
  const repo = new FakeUserRepository();
  // A low cost keeps the tests fast; the hashing itself is real.
  const service = new UserService(repo, new PasswordHasher({ N: 1024, r: 8, p: 1 }));
  return { repo, service };
}

const anna: CreateUserInput = { name: 'Anna', email: 'anna@example.com', password: 'correct horse' };
const isUserError = (status: number) => (err: unknown) => err instanceof UserError && err.status === status;

describe('UserService', () => {
  it('creates a user with a trimmed name, a lower-case email and a hashed password', async () => {
    const { repo, service } = setup();
    const user = await service.create({ ...anna, name: '  Anna ', email: ' Anna@Example.COM ' });

    assert.equal(user.name, 'Anna');
    assert.equal(user.email, 'anna@example.com');
    assert.equal(user.role, 'USER');
    assert.ok(!('password' in user));
    assert.match(repo.hashes.get(user.id)!, /^scrypt\$/);
  });

  it('rejects invalid input with 400', async () => {
    const { service } = setup();
    const invalid: unknown[] = [
      null,
      { email: 'a@b.co', password: 'correct horse' },
      { name: '   ', email: 'a@b.co', password: 'correct horse' },
      { name: 'Anna', email: 'not-an-email', password: 'correct horse' },
      { name: 'Anna', email: 'a@b.co', password: 'correct horse', role: 'OWNER' },
      { name: 'Anna', email: 'a@b.co' },
      { name: 'Anna', email: 'a@b.co', password: 'short' },
      { name: 'Anna', email: 'a@b.co', password: 'x'.repeat(129) },
      { name: 'Anna', email: 'a@b.co', password: 12345678 },
    ];
    for (const input of invalid) {
      await assert.rejects(service.create(input as CreateUserInput), isUserError(400), JSON.stringify(input));
    }
  });

  it('updates only the given fields, but never the password', async () => {
    const { repo, service } = setup();
    const user = await service.create(anna);

    const updated = await service.update(user.id, { role: 'ADMIN' });
    assert.deepEqual(repo.lastUpdate, { role: 'ADMIN' });
    assert.equal(updated.role, 'ADMIN');
    assert.equal(updated.name, 'Anna');

    const withPassword = { password: 'new password' } as UpdateUserInput;
    await assert.rejects(service.update(user.id, withPassword), isUserError(400));
  });

  it('checks a password: the right one gives the user, a wrong one or an unknown email 401', async () => {
    const { service } = setup();
    const user = await service.create(anna);

    assert.deepEqual(await service.checkPassword({ email: ' ANNA@example.com', password: 'correct horse' }), user);
    await assert.rejects(service.checkPassword({ email: 'anna@example.com', password: 'wrong horse' }), isUserError(401));
    await assert.rejects(service.checkPassword({ email: 'nobody@example.com', password: 'correct horse' }), isUserError(401));
    await assert.rejects(service.checkPassword({ email: 'anna@example.com' } as never), isUserError(400));
  });

  it('changes a password: the old one stops working', async () => {
    const { service } = setup();
    const user = await service.create(anna);

    await service.setPassword(user.id, { password: 'battery staple' });
    await assert.rejects(service.checkPassword({ email: anna.email, password: 'correct horse' }), isUserError(401));
    assert.equal((await service.checkPassword({ email: anna.email, password: 'battery staple' })).id, user.id);

    await assert.rejects(service.setPassword(user.id, { password: 'short' }), isUserError(400));
    await assert.rejects(service.setPassword('nope', { password: 'battery staple' }), isUserError(404));
  });

  it('answers 404 for an unknown user', async () => {
    const { service } = setup();
    await assert.rejects(service.get('nope'), isUserError(404));
    await assert.rejects(service.update('nope', { name: 'X' }), isUserError(404));
    await assert.rejects(service.delete('nope'), isUserError(404));
  });
});
