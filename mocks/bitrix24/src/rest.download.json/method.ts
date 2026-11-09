// download.json — the file a DOWNLOAD_URL from disk.file.get points to.
// https://apidocs.bitrix24.com/api-reference/files/how-to-download-files.html

import { getParam } from '#src/utils/params.ts';
import { fileIdFromToken, getRecordFile } from '#src/utils/recordFiles.ts';
import { ApiError } from '#src/utils/types.ts';
import type { RequestContext } from '#src/utils/types.ts';
import { createFileWAV } from '#src/utils/audio.ts';

export function restDownloadJson({ res, params }: RequestContext): void {
  const fileId = fileIdFromToken(String(getParam(params, 'token') ?? ''));
  const file = fileId === null ? undefined : getRecordFile(fileId);
  if (!file) throw new ApiError(404, 'ERROR_NOT_FOUND', 'File not found');

  const wav = createFileWAV(file.durationSec);
  res.writeHead(200, {
    'Content-Type': 'audio/wav',
    'Content-Length': wav.length,
    'Content-Disposition': `attachment; filename="${file.name}"`,
  });
  res.end(wav);
}
