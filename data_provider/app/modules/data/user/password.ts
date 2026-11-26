import { randomBytes, scrypt, timingSafeEqual } from 'node:crypto';
import type { ScryptCost } from './types.ts';

// One of the scrypt settings recommended by OWASP: 32 MiB of memory and about half a second per hash,
// which makes guessing passwords from a stolen database very slow.
const OWASP_COST: ScryptCost = { N: 2 ** 15, r: 8, p: 3 };
const SALT_BYTES = 16;
const HASH_BYTES = 32;

/**
 * Turns passwords into hashes and checks passwords against them. A hash looks like
 * "scrypt$32768$8$3$<salt>$<hash>": a random salt makes equal passwords get different hashes, and the cost
 * is kept with the hash, so the cost of new hashes can be raised later and old ones still work.
 */
export class PasswordHasher {
  #cost: ScryptCost;

  constructor(cost: ScryptCost = OWASP_COST) {
    this.#cost = cost;
  }

  async hash(password: string): Promise<string> {
    const { N, r, p } = this.#cost;
    const salt = randomBytes(SALT_BYTES);
    const hash = await derive(password, salt, HASH_BYTES, this.#cost);
    return ['scrypt', N, r, p, salt.toString('base64'), hash.toString('base64')].join('$');
  }

  /**
   * True if the password matches the hash. Without a usable hash (an unknown user, or one whose password
   * was never set) a hash is still computed, so the answer takes as long and doesn't tell that apart.
   */
  async verify(password: string, stored: string | null): Promise<boolean> {
    const [algorithm, N, r, p, salt, hash] = stored?.split('$') ?? [];
    if (algorithm !== 'scrypt' || !N || !r || !p || !salt || !hash) {
      await this.hash(password);
      return false;
    }
    const expected = Buffer.from(hash, 'base64');
    const actual = await derive(password, Buffer.from(salt, 'base64'), expected.length, {
      N: Number(N),
      r: Number(r),
      p: Number(p),
    });
    // Compares in constant time, so the time taken doesn't hint how much of the hash matched.
    return timingSafeEqual(actual, expected);
  }
}

function derive(password: string, salt: Buffer, length: number, { N, r, p }: ScryptCost): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    // NFC: the same letters typed in different ways (e.g. "й" as one or two characters) give the same hash.
    scrypt(password.normalize('NFC'), salt, length, { N, r, p, maxmem: 256 * N * r }, (err, key) =>
      err ? reject(err) : resolve(key),
    );
  });
}

export const passwordHasher = new PasswordHasher();
