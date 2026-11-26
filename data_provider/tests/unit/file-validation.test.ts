import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { detectFormat } from '#app/modules/data/file/validation.ts';

const bytes = (...parts: (string | number[])[]) =>
  Buffer.concat(parts.map((p) => (typeof p === 'string' ? Buffer.from(p, 'latin1') : Buffer.from(p))));

describe('detectFormat', () => {
  it('recognises audio formats by their content', () => {
    const cases: [Buffer, string][] = [
      [bytes('RIFF', [0, 0, 0, 0], 'WAVE', 'fmt '), 'wav'],
      [bytes('ID3', [4, 0, 0]), 'mp3'],
      [bytes([0xff, 0xfb, 0x90, 0x00]), 'mp3'],
      [bytes('OggS', [0, 2]), 'ogg'],
      [bytes('fLaC', [0, 0]), 'flac'],
      [bytes([0, 0, 0, 0x20], 'ftypM4A '), 'm4a'],
    ];
    for (const [data, extension] of cases) {
      assert.equal(detectFormat('call_recording', data)?.extension, extension);
    }
  });

  it('rejects content that is not audio for a call recording', () => {
    assert.equal(detectFormat('call_recording', bytes('hello, this is text')), null);
    assert.equal(detectFormat('call_recording', bytes('RIFF', [0, 0, 0, 0], 'AVI ')), null);
  });

  it('accepts only valid JSON for a transcription', () => {
    assert.deepEqual(detectFormat('transcription', bytes('{"text":"hello"}')), {
      contentType: 'application/json',
      extension: 'json',
    });
    assert.equal(detectFormat('transcription', bytes('{oops')), null);
  });
});
