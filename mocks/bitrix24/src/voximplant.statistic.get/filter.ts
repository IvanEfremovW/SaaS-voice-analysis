// FILTER / SORT / ORDER of voximplant.statistic.get, as described in
// https://apidocs.bitrix24.com/api-reference/telephony/voximplant/voximplant-statistic-get.html

import { parseDate } from '#src/utils/time.ts';
import { ApiError } from '#src/utils/types.ts';
import type { ParamValue } from '#src/utils/types.ts';
import type { CallRecord, Condition, FieldType, FilterValue, Operator, Order } from './types.ts';

/**
 * "Available Fields for Filtering" with their documented types.
 */
const FILTER_FIELDS: Readonly<Record<string, FieldType>> = {
  ID: 'int',
  CALL_ID: 'string',
  EXTERNAL_CALL_ID: 'string',
  CALL_CATEGORY: 'string',
  PORTAL_USER_ID: 'int',
  PORTAL_NUMBER: 'string',
  PHONE_NUMBER: 'string',
  CALL_TYPE: 'int',
  CALL_DURATION: 'int',
  CALL_START_DATE: 'datetime',
  CALL_LOG: 'string',
  CALL_RECORD_URL: 'string',
  CALL_VOTE: 'int',
  COST: 'double',
  COST_CURRENCY: 'string',
  CALL_FAILED_CODE: 'string',
  CALL_FAILED_REASON: 'string',
  CRM_ENTITY_TYPE: 'string',
  CRM_ENTITY_ID: 'int',
  CRM_ACTIVITY_ID: 'int',
  REST_APP_ID: 'int',
  REST_APP_NAME: 'string',
  TRANSCRIPT_ID: 'int',
  TRANSCRIPT_PENDING: 'string',
  SESSION_ID: 'int',
  REDIAL_ATTEMPT: 'int',
  COMMENT: 'string',
  RECORD_DURATION: 'int',
};

/**
 * Longest first, so "!><" is not read as "!".
 */
const OPERATORS: readonly Operator[] = ['!><', '><', '>=', '<=', '!=', '!%', '!', '>', '<', '=', '%', '?'];

const invalidError = (message: string) => new ApiError(400, 'ERROR_ARGUMENT', message);

// ---------------------------------------------------------------------------------------------
// Parsing

export function parseFilter(raw: ParamValue | undefined): Condition[] {
  if (raw === undefined || raw === null || raw === '' || (Array.isArray(raw) && raw.length === 0)) return [];
  if (typeof raw !== 'object' || Array.isArray(raw)) throw invalidError('FILTER must be an object');

  return Object.entries(raw).map(([key, value]) => {
    const op = OPERATORS.find((o) => key.startsWith(o)) ?? '=';
    const field = key.slice(key.startsWith(op) ? op.length : 0).toUpperCase();
    const type = FILTER_FIELDS[field];
    if (type === undefined) throw invalidError(`Unknown filter field "${key}"`);

    const values = (Array.isArray(value) ? value : [value]).map((v) => toFilterValue(type, v, key));
    if ((op === '><' || op === '!><') && values.length !== 2) throw invalidError(`FILTER[${key}] must be [from, to]`);
    if (['>', '>=', '<', '<='].includes(op) && values.length !== 1) throw invalidError(`FILTER[${key}] must be a single value`);
    return { field, op, values };
  });
}

export function parseSort(rawSort: ParamValue | undefined, rawOrder: ParamValue | undefined): { field: string; order: Order } | null {
  if (rawSort === undefined || rawSort === null || rawSort === '') return null;
  const field = String(rawSort).toUpperCase();
  // SORT accepts the filter fields except CALL_TYPE.
  if (!(field in FILTER_FIELDS) || field === 'CALL_TYPE') throw invalidError(`SORT field "${String(rawSort)}" is not supported`);
  const order = String(rawOrder || 'ASC').toUpperCase();
  if (order !== 'ASC' && order !== 'DESC') throw invalidError('ORDER must be ASC or DESC');
  return { field, order };
}

function toFilterValue(type: FieldType, raw: ParamValue, key: string): FilterValue {
  if (raw === null || raw === '') return null;
  if (typeof raw === 'object') throw invalidError(`invalidError value for FILTER[${key}]`);
  const s = String(raw);
  if (type === 'int' || type === 'double') {
    const n = Number(s);
    if (Number.isNaN(n)) throw invalidError(`FILTER[${key}] must be a number, got "${s}"`);
    return n;
  }
  if (type === 'datetime') {
    const ms = parseDate(s);
    if (ms === null) throw invalidError(`FILTER[${key}] must be an ISO-8601 date, got "${s}"`);
    return ms;
  }
  return s;
}

// ---------------------------------------------------------------------------------------------
// Matching and sorting

/**
 * A record field converted the same way as filter values, so the two can be compared.
 */
function fieldValue(call: CallRecord, field: string): FilterValue {
  const raw = call[field as keyof CallRecord];
  if (raw === null || raw === undefined || raw === '') return null;
  const type = FILTER_FIELDS[field];
  if (type === 'int' || type === 'double') return Number(raw);
  if (type === 'datetime') return parseDate(String(raw));
  return String(raw);
}

function contains(haystack: FilterValue, needle: FilterValue): boolean {
  if (haystack === null || needle === null) return false;
  return String(haystack).toLowerCase().includes(String(needle).toLowerCase());
}

function matches(call: CallRecord, c: Condition): boolean {
  const x = fieldValue(call, c.field);
  const [a = null, b = null] = c.values;
  switch (c.op) {
    case '=':
      return c.values.includes(x);
    case '!':
    case '!=':
      return !c.values.includes(x);
    case '>':
      return x !== null && a !== null && x > a;
    case '>=':
      return x !== null && a !== null && x >= a;
    case '<':
      return x !== null && a !== null && x < a;
    case '<=':
      return x !== null && a !== null && x <= a;
    case '><':
      return x !== null && a !== null && b !== null && x >= a && x <= b;
    case '!><':
      return x !== null && a !== null && b !== null && (x < a || x > b);
    case '%':
    case '?': // "string search", simplified to a substring match
      return c.values.some((v) => contains(x, v));
    case '!%':
      return !c.values.some((v) => contains(x, v));
  }
}

export function matchesAll(call: CallRecord, conditions: readonly Condition[]): boolean {
  return conditions.every((c) => matches(call, c));
}

/**
 * Like SQL ORDER BY: empty values first in ASC, last in DESC. Ties keep ID order.
 */
export function sortCalls(calls: readonly CallRecord[], field: string, order: Order): CallRecord[] {
  const dir = order === 'ASC' ? 1 : -1;
  return [...calls].sort((c1, c2) => {
    const a = fieldValue(c1, field);
    const b = fieldValue(c2, field);
    if (a !== b) {
      if (a === null) return -dir;
      if (b === null) return dir;
      if (a < b) return -dir;
      if (a > b) return dir;
    }
    return Number(c1.ID) - Number(c2.ID);
  });
}

// ---------------------------------------------------------------------------------------------
// Helpers for the generator: which values / ranges the filter allows for a field

/**
 * Values a field is pinned to by an "=" condition, or null if it is not pinned.
 */
export function pinnedValues(conditions: readonly Condition[], field: string): FilterValue[] | null {
  return conditions.find((c) => c.field === field && c.op === '=')?.values ?? null;
}

/**
 * Numeric range a field is limited to by >=, >, <=, <, >< conditions.
 */
export function bounds(conditions: readonly Condition[], field: string): { lo: number | null; hi: number | null } {
  let lo: number | null = null;
  let hi: number | null = null;
  for (const c of conditions) {
    if (c.field !== field) continue;
    const [a, b] = c.values;
    const from = c.op === '>=' || c.op === '>' || c.op === '><' ? a : undefined;
    const to = c.op === '<=' || c.op === '<' ? a : c.op === '><' ? b : undefined;
    if (typeof from === 'number') lo = lo === null ? from : Math.max(lo, from);
    if (typeof to === 'number') hi = hi === null ? to : Math.min(hi, to);
  }
  return { lo, hi };
}
