// Small seeded PRNG helpers, so the same query always produces the same data.

export type Rng = () => number;

/** mulberry32: fast 32-bit seeded generator, returns floats in [0, 1). */
export function createRng(seed: number): Rng {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** FNV-1a 32-bit hash of a string. */
export function hashString(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** Integer in [min, max], both inclusive. */
export function randInt(rng: Rng, min: number, max: number): number {
  return min + Math.floor(rng() * (max - min + 1));
}

export function pick<T>(rng: Rng, items: readonly T[]): T {
  const item = items[Math.floor(rng() * items.length)];
  if (item === undefined) throw new Error('pick() from an empty list');
  return item;
}

export function weighted<T>(rng: Rng, entries: readonly (readonly [T, number])[]): T {
  const total = entries.reduce((sum, [, w]) => sum + w, 0);
  let r = rng() * total;
  for (const [value, w] of entries) {
    r -= w;
    if (r < 0) return value;
  }
  const last = entries[entries.length - 1];
  if (last === undefined) throw new Error('weighted() from an empty list');
  return last[0];
}

export function randomHex(rng: Rng, length: number): string {
  let s = '';
  for (let i = 0; i < length; i++) s += Math.floor(rng() * 16).toString(16);
  return s;
}

export function randomDigits(rng: Rng, length: number): string {
  let s = String(randInt(rng, 1, 9));
  for (let i = 1; i < length; i++) s += String(randInt(rng, 0, 9));
  return s;
}
