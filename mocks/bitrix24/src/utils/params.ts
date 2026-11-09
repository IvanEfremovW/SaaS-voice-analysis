// Reads method parameters. Bitrix24 accepts them in the query string (PHP-style:
// FILTER[>=CALL_START_DATE]=...&FILTER[ID][]=1) or in a JSON / form-encoded POST body.

import type { IncomingMessage } from 'node:http';
import { ApiError } from './types.ts';
import type { ParamObject, ParamValue } from './types.ts';

export async function readParams(req: IncomingMessage, url: URL): Promise<ParamObject> {
  const params = parseQueryString(url.search);
  const body = await readBody(req);
  if (body === '') return params;

  const contentType = req.headers['content-type'] ?? '';
  if (contentType.includes('application/json')) {
    try {
      return { ...params, ...toArrays(JSON.parse(body)) as ParamObject };
    } catch {
      throw new ApiError(400, 'INVALID_REQUEST', 'Request body is not valid JSON');
    }
  }
  if (contentType.includes('application/x-www-form-urlencoded')) {
    return { ...params, ...parseQueryString(body) };
  }
  return params;
}

/** Case-insensitive lookup: clients send both FILTER and filter. */
export function getParam(params: ParamObject, name: string): ParamValue | undefined {
  const key = Object.keys(params).find((k) => k.toLowerCase() === name.toLowerCase());
  return key === undefined ? undefined : params[key];
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (chunk: Buffer) => chunks.push(chunk));
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

/** "FILTER[>=CALL_START_DATE]=x&FILTER[ID][]=1" -> { FILTER: { '>=CALL_START_DATE': 'x', ID: ['1'] } } */
function parseQueryString(qs: string): ParamObject {
  const out: ParamObject = {};
  for (const [key, value] of new URLSearchParams(qs)) {
    const path = key.split(/[[\]]+/).filter((part, i) => i === 0 || part !== '' || key.endsWith('[]'));
    let node = out;
    path.forEach((part, i) => {
      const k = part === '' ? String(Object.keys(node).length) : part; // "a[]" appends
      if (i === path.length - 1) {
        node[k] = value;
      } else {
        const next = node[k];
        node = next !== null && typeof next === 'object' && !Array.isArray(next) ? next : (node[k] = {});
      }
    });
  }
  return toArrays(out) as ParamObject;
}

/** Objects with keys "0", "1", ... become arrays, like in PHP. */
function toArrays(value: ParamValue): ParamValue {
  if (value === null || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map(toArrays);
  const keys = Object.keys(value);
  const converted = keys.map((k) => toArrays(value[k] ?? null));
  if (keys.length > 0 && keys.every((k, i) => k === String(i))) return converted;
  return Object.fromEntries(keys.map((k, i) => [k, converted[i] ?? null]));
}
