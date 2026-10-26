// Portal timezone handling. Bitrix24 returns dates in ISO-8601 with the portal's offset.

import config from '#config' with { type: 'json' };

function parseOffset(raw: string): number {
  const m = /^([+-])(\d{2}):(\d{2})$/.exec(raw);
  if (!m) throw new Error(`utils.time.TZ_OFFSET in mock_config.json must look like +03:00, got "${raw}"`);
  const minutes = Number(m[2]) * 60 + Number(m[3]);
  return m[1] === '-' ? -minutes : minutes;
}

const { TZ_OFFSET } = config.utils.time;
const offsetMinutes = parseOffset(TZ_OFFSET);

const pad = (n: number): string => String(n).padStart(2, '0');

/** Formats a timestamp as "2025-08-06T14:08:40+03:00" in the portal timezone. */
export function formatDate(ms: number): string {
  const d = new Date(ms + offsetMinutes * 60_000);
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` +
    `T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}${TZ_OFFSET}`
  );
}

/** Hour of day (0-23) of a timestamp in the portal timezone. */
export function localHour(ms: number): number {
  return new Date(ms + offsetMinutes * 60_000).getUTCHours();
}

/**
 * Parses a date passed in a filter. Returns epoch ms or null if the value is not a date.
 * 
 * Dates without an offset are treated as portal-local time, like Bitrix24 does.
 */
export function parseDate(value: string): number | null {
  // "+03:00" in an unencoded query string arrives as " 03:00".
  let s = value.trim().replace(/ (\d{2}:\d{2})$/, '+$1');
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) s += `T00:00:00${TZ_OFFSET}`;
  else if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?$/.test(s)) s = s.replace(' ', 'T') + TZ_OFFSET;
  const ms = Date.parse(s);
  return Number.isNaN(ms) ? null : ms;
}
