// disk.file.get — Drive file of a call recording, with the link to download it.
// https://apidocs.bitrix24.com/api-reference/disk/file/disk-file-get.html

import config from '#config' with { type: 'json' };
import { wavSize } from '#src/utils/audio.ts';
import { getParam } from '#src/utils/params.ts';
import { downloadUrl, getRecordFile } from '#src/utils/recordFiles.ts';
import { sendJson, timeInfo } from '#src/utils/response.ts';
import { formatDate } from '#src/utils/time.ts';
import { ApiError } from '#src/utils/types.ts';
import type { RequestContext } from '#src/utils/types.ts';

/** Recordings live on the company Drive, in the telephony recordings folder. */
const { STORAGE_ID, FOLDER_ID, FOLDER_NAME } = config['disk.file.get'].method;

export function diskFileGet({ res, params, baseUrl, startedAtMs }: RequestContext): void {
  const id = Number(getParam(params, 'id'));
  if (!Number.isInteger(id) || id <= 0) {
    throw new ApiError(400, 'ERROR_ARGUMENT', 'Invalid value of parameter {Parameter #0}');
  }
  const file = getRecordFile(id);
  if (!file) throw new ApiError(404, 'ERROR_NOT_FOUND', `Could not find entity with id \`${id}\``);

  const created = formatDate(file.createdAtMs);
  sendJson(res, 200, {
    result: {
      ID: String(file.id),
      NAME: file.name,
      CODE: null,
      STORAGE_ID,
      TYPE: 'file',
      PARENT_ID: FOLDER_ID,
      DELETED_TYPE: '0',
      GLOBAL_CONTENT_VERSION: '1',
      FILE_ID: String(file.id),
      SIZE: String(wavSize(file.durationSec)),
      CREATE_TIME: created,
      UPDATE_TIME: created,
      DELETE_TIME: null,
      CREATED_BY: file.createdBy,
      UPDATED_BY: file.createdBy,
      DELETED_BY: '0',
      DOWNLOAD_URL: downloadUrl(baseUrl, file.id),
      DETAIL_URL: `${baseUrl}/docs/file/${encodeURIComponent(FOLDER_NAME)}/${encodeURIComponent(file.name)}`,
    },
    time: timeInfo(startedAtMs),
  });
}
