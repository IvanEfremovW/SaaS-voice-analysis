import { NavLink, Outlet, useNavigation } from 'react-router';
import { useCurrentUser } from '#frontend/currentUser.ts';

export function Layout() {
  const user = useCurrentUser();
  // Not "idle" while the next page loads or a form is being sent.
  const navigation = useNavigation();

  return (
    <div className="layout">
      <nav className="sidebar">
        <p className="app-name">Анализ звонков</p>

        <h3>Общее</h3>
        <ul>
          <li>
            <NavLink to="/calls">Звонки</NavLink>
          </li>
          <li>
            <NavLink to="/user">Профиль</NavLink>
          </li>
        </ul>

        {user.role === 'ADMIN' && (
          <>
            <h3>Администрирование</h3>
            <ul>
              <li>
                <NavLink to="/users">Пользователи</NavLink>
              </li>
            </ul>
          </>
        )}
      </nav>

      <main className={navigation.state === 'idle' ? undefined : 'busy'}>
        <Outlet />
      </main>
    </div>
  );
}
