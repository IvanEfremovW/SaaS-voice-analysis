import { useCurrentUser } from '#frontend/currentUser.ts';
import { ROLE_LABELS } from '#frontend/format.ts';

export function UserPage() {
  const user = useCurrentUser();

  return (
    <>
      <h1>Профиль</h1>
      <table className="details">
        <tbody>
          <tr>
            <th>Имя</th>
            <td>{user.name}</td>
          </tr>
          <tr>
            <th>Email</th>
            <td>{user.email}</td>
          </tr>
          <tr>
            <th>Роль</th>
            <td>{ROLE_LABELS[user.role]}</td>
          </tr>
        </tbody>
      </table>
    </>
  );
}
