import { Form, Link, useActionData, useLoaderData, useNavigation } from 'react-router';
import { useCurrentUser } from '#frontend/currentUser.ts';
import { ROLE_LABELS, formatDate } from '#frontend/format.ts';
import type { usersAction, usersLoader } from './route.ts';

export function UsersPage() {
  const { users, calls } = useLoaderData<typeof usersLoader>();
  const result = useActionData<typeof usersAction>();
  const me = useCurrentUser();
  const navigation = useNavigation();

  return (
    <>
      <h1>Пользователи</h1>
      {result?.error && <p className="error">{result.error}</p>}

      <table>
        <thead>
          <tr>
            <th>Имя</th>
            <th>Email</th>
            <th>Роль</th>
            <th>Звонки</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => {
            const userCalls = calls.filter((call) => call.userId === user.id);
            return (
              <tr key={user.id}>
                <td>{user.name}</td>
                <td>{user.email}</td>
                <td>{ROLE_LABELS[user.role]}</td>
                <td>
                  {userCalls.length === 0 ? (
                    <span className="muted">нет</span>
                  ) : (
                    // <details> opens and closes by itself, no state needed.
                    <details>
                      <summary>Звонков: {userCalls.length}</summary>
                      <ul>
                        {userCalls.map((call) => (
                          <li key={call.id}>
                            <Link to={`/call/${call.id}`}>{formatDate(call.startedAt)}</Link>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </td>
                <td>
                  {/* Each row has its own small form; the hidden field tells usersAction which user. */}
                  <Form
                    method="post"
                    onSubmit={(event) => {
                      if (!confirm(`Удалить пользователя ${user.name}?`)) event.preventDefault();
                    }}
                  >
                    <input type="hidden" name="id" value={user.id} />
                    <button type="submit" disabled={user.id === me.id || navigation.state !== 'idle'}>
                      Удалить
                    </button>
                  </Form>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}
