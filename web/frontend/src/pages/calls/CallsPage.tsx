import type { ReactNode } from 'react';
import { Form, Link, useLoaderData, useSearchParams } from 'react-router';
import type { CallSort } from '#backend/modules/call/entity.ts';
import { StatusBadge } from '#frontend/components/StatusBadge.tsx';
import { DIRECTION_LABELS, formatDate, formatDuration } from '#frontend/format.ts';
import type { callsLoader } from './route.ts';

export function CallsPage() {
  // What callsLoader returned: the page is drawn only once the calls have arrived.
  const { calls, users, sort, order } = useLoaderData<typeof callsLoader>();
  const [searchParams] = useSearchParams();
  const value = (name: string) => searchParams.get(name) ?? '';

  return (
    <>
      <h1>Звонки</h1>

      {/* A plain GET form: "Показать" puts its fields into the URL (/calls?userId=...), so the loader runs again.
          The key draws the form anew when the URL changes some other way, e.g. by "Сбросить" or "Back". */}
      <Form key={searchParams.toString()} className="filters">
        <label>
          Сотрудник
          <select name="userId" defaultValue={value('userId')}>
            <option value="">Все</option>
            {users.map((user) => (
              <option key={user.id} value={user.id}>
                {user.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Направление
          <select name="direction" defaultValue={value('direction')}>
            <option value="">Все</option>
            <option value="INCOMING">{DIRECTION_LABELS.INCOMING}</option>
            <option value="OUTGOING">{DIRECTION_LABELS.OUTGOING}</option>
          </select>
        </label>
        <label>
          С
          <input type="date" name="from" defaultValue={value('from')} />
        </label>
        <label>
          По
          <input type="date" name="to" defaultValue={value('to')} />
        </label>
        {/* Keeps the sort when the filter changes. */}
        <input type="hidden" name="sort" value={sort} />
        <input type="hidden" name="order" value={order} />
        <button type="submit">Показать</button>
        <Link to="/calls">Сбросить</Link>
      </Form>

      {calls.length === 0 ? (
        <p className="muted">Звонков нет</p>
      ) : (
        <table>
          <thead>
            <tr>
              <SortableTh column="startedAt">Дата</SortableTh>
              <SortableTh column="userName">Сотрудник</SortableTh>
              <SortableTh column="clientPhone">Клиент</SortableTh>
              <SortableTh column="direction">Направление</SortableTh>
              <SortableTh column="durationSec">Длительность</SortableTh>
              <SortableTh column="status">Статус</SortableTh>
            </tr>
          </thead>
          <tbody>
            {calls.map((call) => (
              <tr key={call.id}>
                <td>
                  <Link to={`/call/${call.id}`}>{formatDate(call.startedAt)}</Link>
                </td>
                <td>{call.userName}</td>
                <td>{call.clientPhone}</td>
                <td>{DIRECTION_LABELS[call.direction]}</td>
                <td>{formatDuration(call.durationSec)}</td>
                <td>
                  <StatusBadge status={call.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

/**
 * A column header that is a link to the same URL with another sort. The first click sorts the column
 * from the largest (the newest) down, the next one the other way.
 */
function SortableTh({ column, children }: { column: CallSort; children: ReactNode }) {
  const { sort, order } = useLoaderData<typeof callsLoader>();
  const [searchParams] = useSearchParams();

  const active = sort === column;
  const next = new URLSearchParams(searchParams);
  next.set('sort', column);
  next.set('order', active && order === 'desc' ? 'asc' : 'desc');

  return (
    <th>
      <Link to={`?${next}`}>
        {children} {active ? (order === 'desc' ? '▼' : '▲') : <span className="muted">↕</span>}
      </Link>
    </th>
  );
}
