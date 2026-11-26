import { useRouteError } from 'react-router';
import { HttpError } from '#frontend/api.ts';

const TITLES: Record<number, string> = {
  401: 'Вы не вошли',
  403: 'Нет доступа',
  404: 'Не найдено',
};

export function ErrorPage() {
  const error = useRouteError();

  // An error answer of the backend (thrown by api.ts), or an unknown URL.
  if (error instanceof HttpError) {
    return (
      <div className="error-page">
        <h2>{TITLES[error.status] ?? 'Не удалось загрузить данные'}</h2>
        <p>{error.message}</p>
      </div>
    );
  }

  // Anything else: the backend is unreachable, or a bug in the page.
  console.error(error);
  return (
    <div className="error-page">
      <h2>Что-то пошло не так</h2>
      <p>{error instanceof Error ? error.message : String(error)}</p>
    </div>
  );
}
