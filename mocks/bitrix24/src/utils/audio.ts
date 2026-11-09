// Content of a call recording: a WAV file with random noise, mono 16-bit (8 kHz = telephony quality).
// To serve real speech instead, replace this file and keep the two exported functions.

import config from '#config' with { type: 'json' };

const { SAMPLE_RATE, NOISE_AMPLITUDE } = config.utils.audio;
const BYTES_PER_SAMPLE = 2;
const HEADER_BYTES = 44;

export function wavSize(durationSec: number): number {
  return HEADER_BYTES + durationSec * SAMPLE_RATE * BYTES_PER_SAMPLE;
}

/** Generates a file in .WAV format */
export function createFileWAV(durationSec: number): Buffer {
  const dataBytes = durationSec * SAMPLE_RATE * BYTES_PER_SAMPLE;
  const wav = Buffer.alloc(HEADER_BYTES + dataBytes);

  wav.write('RIFF', 0, 'ascii');
  wav.writeUInt32LE(36 + dataBytes, 4);
  wav.write('WAVE', 8, 'ascii');
  wav.write('fmt ', 12, 'ascii');
  wav.writeUInt32LE(16, 16); // size of the fmt chunk
  wav.writeUInt16LE(1, 20); // PCM
  wav.writeUInt16LE(1, 22); // mono
  wav.writeUInt32LE(SAMPLE_RATE, 24);
  wav.writeUInt32LE(SAMPLE_RATE * BYTES_PER_SAMPLE, 28); // bytes per second
  wav.writeUInt16LE(BYTES_PER_SAMPLE, 32); // bytes per sample frame
  wav.writeUInt16LE(16, 34); // bits per sample
  wav.write('data', 36, 'ascii');
  wav.writeUInt32LE(dataBytes, 40);

  for (let offset = HEADER_BYTES; offset < wav.length; offset += BYTES_PER_SAMPLE) {
    wav.writeInt16LE(Math.round((Math.random() * 2 - 1) * NOISE_AMPLITUDE), offset);
  }
  return wav;
}
