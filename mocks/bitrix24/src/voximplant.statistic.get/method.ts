// voximplant.statistic.get — list of calls with metadata.
// https://apidocs.bitrix24.com/api-reference/telephony/voximplant/voximplant-statistic-get.html

import { randomInt } from 'node:crypto';
import config from '#config' with { type: 'json' };
import { getParam } from '#src/utils/params.ts';
import { sendJson, timeInfo } from '#src/utils/response.ts';
import { hashString } from './rng.ts';
import type { RequestContext } from '#src/utils/types.ts';
import { parseFilter, parseSort, sortCalls } from './filter.ts';
import { generateCalls } from './generator.ts';
import type { CallRecord, Condition } from './types.ts';

const PAGE_SIZE = 50;
/** Same seed + same FILTER => same calls. With SEED null the data changes on every restart. */
const SEED = config['voximplant.statistic.get'].method.SEED ?? randomInt(1, 2 ** 31);

/** Generated calls per FILTER, so paging with `start` walks over the same calls. */
const callsByFilter = new Map<string, CallRecord[]>();

function getCalls(conditions: Condition[], nowMs: number): CallRecord[] {
  const key = JSON.stringify(conditions);
  let calls = callsByFilter.get(key);
  if (!calls) {
    calls = generateCalls(conditions, hashString(`${SEED}:${key}`), nowMs);
    callsByFilter.set(key, calls);
  }
  return calls;
}

export function voximplantStatisticGet({ res, params, startedAtMs }: RequestContext): void {
  const conditions = parseFilter(getParam(params, 'FILTER'));
  const sort = parseSort(getParam(params, 'SORT'), getParam(params, 'ORDER'));

  const calls = getCalls(conditions, startedAtMs);
  const sorted = sort ? sortCalls(calls, sort.field, sort.order) : calls;

  const start = Math.max(0, Number(getParam(params, 'start')) || 0);
  const next = start + PAGE_SIZE;

  sendJson(res, 200, {
    result: sorted.slice(start, next),
    ...(next < sorted.length ? { next } : {}),
    total: sorted.length,
    time: timeInfo(startedAtMs),
  });
}
