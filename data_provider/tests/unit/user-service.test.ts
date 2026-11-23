import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { describe, it } from 'node:test';
import type { DatabaseClient } from '#app/infrastructure/database.ts';
import { UserError } from '#app/modules/data/user/entity.ts';
import type { CreateUserInput, UpdateUserInput, User } from '#app/modules/data/user/entity.ts';
import { UserRepository } from '#app/modules/data/user/repository.ts';
import { UserService } from '#app/modules/data/user/service.ts';

class FakeUserRepository extends UserRepository {
  users = new Map<string, User>();
  lastUpdate: UpdateUserInput | undefined;

  constructor() {
    super({} as DatabaseClient);
  }

  override async create(input: CreateUserInput): Promise<User> {
    const now = new Date().toISOString();
    const user: User = { id: randomUUID(), role: 'USER', ...input, createdAt: now, updatedAt: now };
    this.users.set(user.id, user);
    return user;
  }

  override async findById(id: string): Promise<User | null> {
    return this.users.get(id) ?? null;
  }

  override async update(id: string, input: UpdateUserInput): Promise<User | null> {
    this.lastUpdate = input;
    const user = this.users.get(id);
    return user ? { ...user, ...input } : null;
  }

  override async delete(id: string): Promise<boolean> {
    return this.users.delete(id);
  }
}

const isUserError = (status: number) => (err: unknown) => err instanceof UserError && err.status === status;

describe('UserService', () => {
  it('creates a user with a trimmed name and a lower-case email', async () => {
    const user = await new UserService(new FakeUserRepository()).create({ name: '  Anna ', email: ' Anna@Example.COM ' });
    assert.equal(user.name, 'Anna');
    assert.equal(user.email, 'anna@example.com');
    assert.equal(user.role, 'USER');
  });

  it('rejects invalid input with 400', async () => {
    const service = new UserService(new FakeUserRepository());
    const invalid: unknown[] = [
      null,
      { email: 'a@b.co' },
      { name: '   ', email: 'a@b.co' },
      { name: 'Anna', email: 'not-an-email' },
      { name: 'Anna', email: 'a@b.co', role: 'OWNER' },
    ];
    for (const input of invalid) {
      await assert.rejects(service.create(input as CreateUserInput), isUserError(400), JSON.stringify(input));
    }
  });

  it('updates only the given fields', async () => {
    const repo = new FakeUserRepository();
    const service = new UserService(repo);
    const user = await service.create({ name: 'Anna', email: 'anna@example.com' });

    const updated = await service.update(user.id, { role: 'ADMIN' });

    assert.deepEqual(repo.lastUpdate, { role: 'ADMIN' });
    assert.equal(updated.role, 'ADMIN');
    assert.equal(updated.name, 'Anna');
  });

  it('answers 404 for an unknown user', async () => {
    const service = new UserService(new FakeUserRepository());
    await assert.rejects(service.get('nope'), isUserError(404));
    await assert.rejects(service.update('nope', { name: 'X' }), isUserError(404));
    await assert.rejects(service.delete('nope'), isUserError(404));
  });
});
