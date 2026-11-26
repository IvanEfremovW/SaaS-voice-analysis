import type { DataProvider } from '#backend/infrastructure/data-provider.ts';
import type { ProviderUser } from './types.ts';

/** The user routes of data_provider. */
export class UserClient {
  #dataProvider: DataProvider;

  constructor(dataProvider: DataProvider) {
    this.#dataProvider = dataProvider;
  }

  async list(): Promise<ProviderUser[]> {
    return (await this.#dataProvider.get<{ users: ProviderUser[] }>('/users')).users;
  }

  async get(id: string): Promise<ProviderUser> {
    return (await this.#dataProvider.get<{ user: ProviderUser }>(`/users/${encodeURIComponent(id)}`)).user;
  }

  async delete(id: string): Promise<void> {
    await this.#dataProvider.send('DELETE', `/users/${encodeURIComponent(id)}`);
  }
}
