import type { IncomingMessage } from 'node:http';
import { config } from '#backend/config.ts';
import { dataProvider } from '#backend/infrastructure/data-provider.ts';
import { HttpError } from '#backend/infrastructure/http.ts';
import { UserClient } from './client.ts';
import type { User } from './entity.ts';
import type { ProviderUser } from './types.ts';

export class UserService {
  #client: UserClient;
  #currentUserEmail: string;

  constructor(client: UserClient, currentUserEmail: string) {
    this.#client = client;
    this.#currentUserEmail = currentUserEmail;
  }

  async list(): Promise<User[]> {
    return (await this.#client.list()).map(toUser);
  }

  async get(id: string): Promise<User> {
    return toUser(await this.#client.get(id));
  }

  /**
   * The user who sent the request. There is no login yet, so for now it is always the user with
   * CURRENT_USER_EMAIL; with a login, the user will be found by the session cookie of the request.
   */
  async current(_req: IncomingMessage): Promise<User> {
    const user = (await this.list()).find((u) => u.email === this.#currentUserEmail);
    if (!user) throw new HttpError(401, `There is no user ${this.#currentUserEmail} (CURRENT_USER_EMAIL) in data_provider`);
    return user;
  }

  /** Only an admin can delete users, and not themselves. */
  async delete(by: User, id: string): Promise<void> {
    if (by.role !== 'ADMIN') throw new HttpError(403, 'Only an admin can delete users');
    if (by.id === id) throw new HttpError(400, 'You cannot delete yourself');
    await this.#client.delete(id);
  }
}

// Only these fields go to the browser, whatever else data_provider keeps about users.
function toUser(user: ProviderUser): User {
  return { id: user.id, name: user.name, email: user.email, role: user.role };
}

export const userService = new UserService(new UserClient(dataProvider), config.currentUserEmail);
