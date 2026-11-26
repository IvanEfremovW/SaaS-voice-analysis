import type { LoaderFunctionArgs, RouteObject } from 'react-router';
import type { Call, CallSort } from '#backend/modules/call/entity.ts';
import type { User } from '#backend/modules/user/entity.ts';
import { api } from '#frontend/api.ts';
import { CallsPage } from './CallsPage.tsx';

/**
 * Gets the calls, filtered and sorted as the URL says (/calls?userId=...&sort=durationSec&order=asc),
 * and the employees for the filter. Runs before the page is drawn, and again whenever the URL changes.
 */
export async function callsLoader({ request }: LoaderFunctionArgs) {
  const query = new URL(request.url).searchParams;
  const sort = (query.get('sort') || 'startedAt') as CallSort;
  const order = query.get('order') === 'asc' ? 'asc' : 'desc';
  const from = query.get('from');
  const to = query.get('to');

  const [{ calls }, { users }] = await Promise.all([
    api.get<{ calls: Call[] }>('/calls', {
      userId: query.get('userId') ?? undefined,
      direction: query.get('direction') ?? undefined,
      // The form gives days ("2026-11-24") of the browser's time zone; "to" includes its whole day.
      from: from ? startOfDay(from, 0) : undefined,
      to: to ? startOfDay(to, 1) : undefined,
      sort,
      order,
    }),
    api.get<{ users: User[] }>('/users'),
  ]);
  return { calls, users, sort, order };
}

/** The moment the day starts in the browser's time zone, `days` days after `date`. */
function startOfDay(date: string, days: number): string {
  const day = new Date(`${date}T00:00`);
  day.setDate(day.getDate() + days);
  return day.toISOString();
}

export const callsRoute: RouteObject = {
  path: '/calls',
  loader: callsLoader,
  Component: CallsPage,
};
