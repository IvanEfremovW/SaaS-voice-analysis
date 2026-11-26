import assert from 'node:assert/strict';
import type { IncomingMessage } from 'node:http';
import { describe, it } from 'node:test';
import { DataProvider } from '#backend/infrastructure/data-provider.ts';
import type { HttpError } from '#backend/infrastructure/http.ts';
import { UserClient } from '#backend/modules/user/client.ts';
import type { User } from '#backend/modules/user/entity.ts';
import { UserService } from '#backend/modules/user/service.ts';
import type { ProviderUser } from '#backend/modules/user/types.ts';

class FakeUserClient extends UserClient {
  deleted: string[] = [];
  constructor() {
    super(new DataProvider('http://data-provider'));
  }
  override async list(): Promise<ProviderUser[]> {
    const secret = { passwordHash: 'x' };
    return [
      { id: 'u1', name: 'Анна', email: 'anna@example.com', role: 'ADMIN', ...secret },
      { id: 'u2', name: 'Борис', email: 'boris@example.com', role: 'USER', ...secret },
    ];
  }
  override async delete(id: string): Promise<void> {
    this.deleted.push(id);
  }
}

const req = {} as IncomingMessage;
const anna: User = { id: 'u1', name: 'Анна', email: 'anna@example.com', role: 'ADMIN' };
const boris: User = { id: 'u2', name: 'Борис', email: 'boris@example.com', role: 'USER' };

describe('UserService', () => {
  it('gives only the fields meant for the browser', async () => {
    const users = await new UserService(new FakeUserClient(), 'anna@example.com').list();
    assert.deepEqual(users, [anna, boris]);
  });

  it('finds the current user by CURRENT_USER_EMAIL', async () => {
    assert.deepEqual(await new UserService(new FakeUserClient(), 'boris@example.com').current(req), boris);
    await assert.rejects(
      new UserService(new FakeUserClient(), 'nobody@example.com').current(req),
      (err: HttpError) => err.status === 401,
    );
  });

  it('lets only an admin delete users, and not themselves', async () => {
    const client = new FakeUserClient();
    const service = new UserService(client, 'anna@example.com');

    await assert.rejects(service.delete(boris, 'u1'), (err: HttpError) => err.status === 403);
    await assert.rejects(service.delete(anna, 'u1'), (err: HttpError) => err.status === 400);
    await service.delete(anna, 'u2');
    assert.deepEqual(client.deleted, ['u2']);
  });
});
