// Recognises the format from the content itself (its first bytes), not from the name or a header,
// so a renamed or mislabelled file can't get in.

import type { FileType } from './entity.ts';
import type { FileFormat } from './types.ts';

const ascii = (data: Buffer, start: number, end: number) => data.subarray(start, end).toString('latin1');

const AUDIO_FORMATS: { matches: (data: Buffer) => boolean; format: FileFormat }[] = [
  {
    matches: (d) => ascii(d, 0, 4) === 'RIFF' && ascii(d, 8, 12) === 'WAVE',
    format: { contentType: 'audio/wav', extension: 'wav' },
  },
  {
    // ID3 tag, or an MPEG audio frame header (11 set bits)
    matches: (d) => ascii(d, 0, 3) === 'ID3' || (d[0] === 0xff && ((d[1] ?? 0) & 0xe0) === 0xe0),
    format: { contentType: 'audio/mpeg', extension: 'mp3' },
  },
  { matches: (d) => ascii(d, 0, 4) === 'OggS', format: { contentType: 'audio/ogg', extension: 'ogg' } },
  { matches: (d) => ascii(d, 0, 4) === 'fLaC', format: { contentType: 'audio/flac', extension: 'flac' } },
  { matches: (d) => ascii(d, 4, 8) === 'ftyp', format: { contentType: 'audio/mp4', extension: 'm4a' } },
];

/** The format of the content if it is allowed for this file type, otherwise null. */
export function detectFormat(type: FileType, data: Buffer): FileFormat | null {
  if (type === 'transcription') {
    try {
      JSON.parse(data.toString('utf8'));
      return { contentType: 'application/json', extension: 'json' };
    } catch {
      return null;
    }
  }
  return AUDIO_FORMATS.find(({ matches }) => matches(data))?.format ?? null;
}
