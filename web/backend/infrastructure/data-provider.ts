import { config } from '#backend/config.ts';
import { HttpError } from './http.ts';

type Query = Record<string, string | undefined>;

/**
 * Sends requests to data_provider. Errors in a request (4xx) are passed on with the same status,
 * a failure of data_provider itself becomes a 502.
 */
export class DataProvider {
  #baseUrl: string;

  constructor(baseUrl: string) {
    this.#baseUrl = baseUrl;
  }

  /** The JSON answer. */
  async get<T>(path: string, query: Query = {}): Promise<T> {
    return (await this.request('GET', path, { query })).json() as Promise<T>;
  }

  /** The JSON answer, or undefined for an empty one (204). */
  async send<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await this.request(method, path, { body });
    return (res.status === 204 ? undefined : await res.json()) as T;
  }

  /** The answer itself, e.g. to stream a file on. */
  async request(method: string, path: string, { query = {}, body }: { query?: Query; body?: unknown } = {}): Promise<Response> {
    const url = new URL(path, this.#baseUrl);
    for (const [key, value] of Object.entries(query)) if (value) url.searchParams.set(key, value);

    const res = await fetch(url, {
      method,
      ...(body !== undefined && { body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } }),
    });
    if (!res.ok) {
      const error = (await res.json().catch(() => ({}))).error;
      throw new HttpError(res.status < 500 ? res.status : 502, error ?? `data_provider answered ${res.status}`);
    }
    return res;
  }
}

export const dataProvider = new DataProvider(config.dataProviderUrl);
