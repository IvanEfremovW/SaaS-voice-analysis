// https://apidocs.bitrix24.com/api-reference/telephony/voximplant/voximplant-statistic-get.html
// https://apidocs.bitrix24.com/api-reference/disk/file/disk-file-get.html

import { CallError } from './entity.ts';
import type { CallFilter } from './entity.ts';
import type { BitrixCall, BitrixDiskFile } from './types.ts';

export class BitrixCallClient {
  #webhookUrl: string;

  /** @param webhookUrl e.g. "https://portal.bitrix24.ru/rest/1/<webhook code>" */
  constructor(webhookUrl: string) {
    this.#webhookUrl = webhookUrl;
  }

  /** Collects all pages (Bitrix24 returns 50 calls per page). */
  async listCalls(filter: CallFilter): Promise<BitrixCall[]> {
    const calls: BitrixCall[] = [];
    let start: number | undefined = 0;
    while (start !== undefined) {
      const params = new URLSearchParams({ start: String(start) });
      if (filter.from) params.set('FILTER[>=CALL_START_DATE]', filter.from);
      if (filter.to) params.set('FILTER[<CALL_START_DATE]', filter.to);

      const page = await this.#get('voximplant.statistic.get', params);
      calls.push(...page.result);
      start = page.next;
    }
    return calls;
  }

  async getFile(fileId: string): Promise<BitrixDiskFile> {
    const body = await this.#get('disk.file.get', new URLSearchParams({ id: fileId }));
    return body.result;
  }

  /** DOWNLOAD_URL links are short-lived: get one with getFile() right before. */
  async download(url: string): Promise<{ data: Buffer; contentType: string }> {
    const res = await request(url);
    if (!res.ok) throw new CallError(res.status, `Download failed: HTTP ${res.status}`);
    return {
      data: Buffer.from(await res.arrayBuffer()),
      contentType: res.headers.get('content-type') ?? 'application/octet-stream',
    };
  }

  async #get(method: string, params: URLSearchParams) {
    const res = await request(`${this.#webhookUrl}/${method}?${params}`);
    const body = await res.json().catch(() => null);
    if (!res.ok || !body) {
      throw new CallError(res.status === 200 ? 502 : res.status, `${body?.error}: ${body?.error_description}`);
    }
    return body;
  }
}

async function request(url: string): Promise<Response> {
  try {
    return await fetch(url);
  } catch {
    throw new CallError(502, 'Bitrix24 is unreachable');
  }
}
