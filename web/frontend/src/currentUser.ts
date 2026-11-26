import { useRouteLoaderData } from 'react-router';
import type { User } from '#backend/modules/user/entity.ts';
import { api } from '#frontend/api.ts';

/** Gets the logged-in user before any page is drawn; the loader of the root route. */
export async function currentUserLoader() {
  return (await api.get<{ user: User }>('/me')).user;
}

/** The logged-in user, in any page or component. */
export function useCurrentUser(): User {
  return useRouteLoaderData<typeof currentUserLoader>('root')!;
}
