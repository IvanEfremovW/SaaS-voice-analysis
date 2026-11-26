import type { CreateUserInput, User } from './entity.ts';

/** What the repository saves for a new user: the password already hashed. */
export type NewUser = Omit<CreateUserInput, 'password'> & { passwordHash: string };

/** The only shape in which a password hash leaves the repository, to check a password. */
export type UserWithPasswordHash = {
  user: User;
  passwordHash: string;
};

/** How costly scrypt is: N is the memory/CPU cost (a power of 2), r the block size, p the parallelization. */
export type ScryptCost = {
  N: number;
  r: number;
  p: number;
};
