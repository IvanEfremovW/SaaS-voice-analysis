import type { ActionFunctionArgs, RouteObject } from 'react-router';
import type { Call } from '#backend/modules/call/entity.ts';
import type { User } from '#backend/modules/user/entity.ts';
import { HttpError, api } from '#frontend/api.ts';
import { UsersPage } from './UsersPage.tsx';

/** All users, and all calls to show the ones of each user. */
export async function usersLoader() {
  const [{ users }, { calls }] = await Promise.all([
    api.get<{ users: User[] }>('/users'),
    api.get<{ calls: Call[] }>('/calls'),
  ]);
  return { users, calls };
}

/** Runs when the "Удалить" form of a row is sent; then the loader runs again and the list is fresh. */
export async function usersAction({ request }: ActionFunctionArgs) {
  const id = String((await request.formData()).get('id'));
  try {
    await api.delete(`/users/${encodeURIComponent(id)}`);
    return { error: null };
  } catch (err) {
    if (!(err instanceof HttpError)) throw err;
    return { error: err.status === 409 ? 'Нельзя удалить: у пользователя есть звонки' : err.message };
  }
}

export const usersRoute: RouteObject = {
  path: '/users',
  loader: usersLoader,
  action: usersAction,
  Component: UsersPage,
};
