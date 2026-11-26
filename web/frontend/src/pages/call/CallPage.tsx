import { Form, Link, useActionData, useLoaderData, useNavigation } from 'react-router';
import { StatusBadge } from '#frontend/components/StatusBadge.tsx';
import { DIRECTION_LABELS, formatDate, formatDuration, formatSize } from '#frontend/format.ts';
import type { callAction, callLoader } from './route.ts';

export function CallPage() {
  const call = useLoaderData<typeof callLoader>();
  // What callAction returned, once the form has been sent.
  const result = useActionData<typeof callAction>();
  const navigation = useNavigation();
  // A worker is busy with the call (the backend refuses a new transcription then).
  const inProgress = call.status === 'TRANSCRIBING' || call.status === 'ANALYZING';

  return (
    <>
      <p>
        <Link to="/calls">← Все звонки</Link>
      </p>
      <h1>Звонок {call.clientPhone}</h1>

      <section>
        <h2>Информация</h2>
        <table className="details">
          <tbody>
            <tr>
              <th>Дата</th>
              <td>{formatDate(call.startedAt)}</td>
            </tr>
            <tr>
              <th>Сотрудник</th>
              <td>{call.userName}</td>
            </tr>
            <tr>
              <th>Клиент</th>
              <td>{call.clientPhone}</td>
            </tr>
            <tr>
              <th>Направление</th>
              <td>{DIRECTION_LABELS[call.direction]}</td>
            </tr>
            <tr>
              <th>Длительность</th>
              <td>{formatDuration(call.durationSec)}</td>
            </tr>
            <tr>
              <th>Статус</th>
              <td>
                <StatusBadge status={call.status} />
              </td>
            </tr>
            {call.error && (
              <tr>
                <th>Ошибка</th>
                <td>{call.error}</td>
              </tr>
            )}
            <tr>
              <th>Запись</th>
              <td>
                {/* A plain link: the backend answers with the file, and "download" makes the browser save it. */}
                <a href={`/api/calls/${call.id}/recording`} download>
                  {call.recording.name}
                </a>{' '}
                <span className="muted">{formatSize(call.recording.sizeBytes)}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>Транскрибация</h2>
        {call.transcription ? (
          <p>
            <a href={`/api/calls/${call.id}/transcription`} download>
              {call.transcription.file.name}
            </a>{' '}
            <span className="muted">
              {formatSize(call.transcription.file.sizeBytes)}, создана {formatDate(call.transcription.createdAt)}
            </span>
          </p>
        ) : (
          <p className="muted">Транскрибации нет</p>
        )}

        {/* Sends a POST to this page's URL, which runs callAction. */}
        <Form
          method="post"
          onSubmit={(event) => {
            if (call.transcription && !confirm('Текущая транскрибация будет удалена. Продолжить?')) event.preventDefault();
          }}
        >
          <button type="submit" disabled={inProgress || navigation.state !== 'idle'}>
            {call.transcription ? 'Перегенерировать' : 'Сгенерировать'}
          </button>{' '}
          {inProgress && <span className="muted">Звонок сейчас обрабатывается</span>}
          {result?.error === null && <span className="muted">Запрос на транскрибацию отправлен</span>}
          {result?.error && <span className="error">{result.error}</span>}
        </Form>
      </section>
    </>
  );
}
