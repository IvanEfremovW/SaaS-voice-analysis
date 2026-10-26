// Types shared by the server and several methods.

import type { IncomingMessage, ServerResponse } from 'node:http';

/** A request parameter after parsing the query string or body (PHP-style arrays become arrays/objects). */
export type ParamValue = string | number | boolean | null | ParamValue[] | ParamObject;
export type ParamObject = { [key: string]: ParamValue };

/** Everything a method needs to handle one request. */
export type RequestContext = {
  req: IncomingMessage;
  res: ServerResponse;
  params: ParamObject;
  baseUrl: string;
  startedAtMs: number;
};

export type MethodHandler = (ctx: RequestContext) => void | Promise<void>;

/**
 * A call recording "stored on Drive". Created by voximplant.statistic.get,
 * read by disk.file.get and download.json.
 */
export type RecordFile = {
  id: number;
  name: string;
  durationSec: number;
  createdBy: string;
  createdAtMs: number;
};

/** An error answered in the Bitrix24 format: {"error": code, "error_description": message}. */
export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, description: string) {
    super(description);
    this.status = status;
    this.code = code;
  }
}
