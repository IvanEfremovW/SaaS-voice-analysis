import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { PasswordHasher } from '#app/modules/data/user/password.ts';

// A low cost keeps the tests fast; the real hasher uses the OWASP one.
const hasher = new PasswordHasher({ N: 1024, r: 8, p: 1 });

describe('PasswordHasher', () => {
  it('stores the cost and a salt with the hash, never the password', async () => {
    const hash = await hasher.hash('correct horse');
    assert.match(hash, /^scrypt\$1024\$8\$1\$[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+$/);
    assert.ok(!hash.includes('correct horse'));
  });

  it('gives the same password a different hash each time', async () => {
    assert.notEqual(await hasher.hash('correct horse'), await hasher.hash('correct horse'));
  });

  it('accepts only the same password', async () => {
    const hash = await hasher.hash('correct horse');
    assert.equal(await hasher.verify('correct horse', hash), true);
    assert.equal(await hasher.verify('correct horse ', hash), false);
    assert.equal(await hasher.verify('Correct horse', hash), false);
  });

  it('checks a hash made with another cost by the cost stored in it', async () => {
    const cheaper = await new PasswordHasher({ N: 512, r: 4, p: 1 }).hash('correct horse');
    assert.equal(await hasher.verify('correct horse', cheaper), true);
  });

  it('treats differently typed letters as the same password', async () => {
    const composed = 'й'; // one character
    const decomposed = 'й'; // "и" plus a combining mark
    assert.equal(await hasher.verify(decomposed, await hasher.hash(composed)), true);
  });

  it('accepts no password without a usable hash', async () => {
    for (const stored of [null, '', 'plain text', 'md5$abc']) {
      assert.equal(await hasher.verify('', stored), false, String(stored));
    }
  });
});
