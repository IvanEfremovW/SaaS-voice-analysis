/** An error answer of the backend. Thrown while a page loads, it makes React Router draw ErrorPage. */
export class HttpError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Every request to the backend goes through here, so things like "on a 401 go to the login page"
// can later be added in this one place.
async function request<T>(method: string, path: string): Promise<T> {
  const res = await fetch(`/api${path}`, { method });
  const body = res.status === 204 ? undefined : await res.json().catch(() => ({}));
  if (!res.ok) throw new HttpError(res.status, body?.error ?? `Ошибка сервера (${res.status})`);
  return body as T;
}

export const api = {
  /** Empty query values are left out. */
  get<T>(path: string, query: Record<string, string | undefined> = {}): Promise<T> {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) if (value) params.set(key, value);
    const search = params.toString();
    return request<T>('GET', search ? `${path}?${search}` : path);
  },
  post: (path: string) => request<void>('POST', path),
  delete: (path: string) => request<void>('DELETE', path),
};
