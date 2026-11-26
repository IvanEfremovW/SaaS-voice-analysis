import { database } from '#app/infrastructure/database.ts';
import { USER_ROLES, UserError } from './entity.ts';
import type { CheckPasswordInput, CreateUserInput, UpdateUserInput, User } from './entity.ts';
import { PasswordHasher, passwordHasher } from './password.ts';
import { UserRepository } from './repository.ts';

const PASSWORD_LENGTH = { min: 8, max: 128 };

export class UserService {
  #users: UserRepository;
  #passwords: PasswordHasher;

  constructor(users: UserRepository, passwords: PasswordHasher) {
    this.#users = users;
    this.#passwords = passwords;
  }

  async create(input: CreateUserInput): Promise<User> {
    const fields = validate(input, true) as Omit<CreateUserInput, 'password'>;
    const passwordHash = await this.#passwords.hash(validatePassword(input.password));
    return this.#users.create({ ...fields, passwordHash });
  }

  async get(id: string): Promise<User> {
    return (await this.#users.findById(id)) ?? notFound(id);
  }

  async list(): Promise<User[]> {
    return this.#users.list();
  }

  async update(id: string, input: UpdateUserInput): Promise<User> {
    return (await this.#users.update(id, validate(input, false))) ?? notFound(id);
  }

  /** Who may change a password (only an admin) is decided by the caller, which knows who is logged in. */
  async setPassword(id: string, input: { password: string }): Promise<void> {
    if (typeof input !== 'object' || input === null) throw new UserError(400, 'Body must be a JSON object');
    const passwordHash = await this.#passwords.hash(validatePassword(input.password));
    if (!(await this.#users.setPasswordHash(id, passwordHash))) notFound(id);
  }

  /** The user with this email and password. A wrong email and a wrong password get the same answer. */
  async checkPassword(input: CheckPasswordInput): Promise<User> {
    if (typeof input !== 'object' || input === null) throw new UserError(400, 'Body must be a JSON object');
    const { email, password } = input;
    if (typeof email !== 'string' || typeof password !== 'string') {
      throw new UserError(400, '"email" and "password" must be strings');
    }
    const found = await this.#users.findWithPasswordHash(email.trim().toLowerCase());
    const matches = await this.#passwords.verify(password, found?.passwordHash ?? null);
    if (!found || !matches) throw new UserError(401, 'Wrong email or password');
    return found.user;
  }

  async delete(id: string): Promise<void> {
    if (!(await this.#users.delete(id))) notFound(id);
  }
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Checks the input at runtime (it comes from JSON) and returns only the known fields, without the password. */
function validate(input: UpdateUserInput, isCreate: boolean): UpdateUserInput {
  if (typeof input !== 'object' || input === null) throw new UserError(400, 'Body must be a JSON object');
  if (!isCreate && 'password' in input) throw new UserError(400, 'The password is changed with PUT /users/:id/password');
  const result: UpdateUserInput = {};

  if (input.name !== undefined || isCreate) {
    if (typeof input.name !== 'string' || !input.name.trim()) throw new UserError(400, '"name" must be a non-empty string');
    result.name = input.name.trim();
  }
  if (input.email !== undefined || isCreate) {
    if (typeof input.email !== 'string' || !EMAIL.test(input.email.trim())) {
      throw new UserError(400, '"email" must be a valid email address');
    }
    result.email = input.email.trim().toLowerCase();
  }
  if (input.role !== undefined) {
    if (!USER_ROLES.includes(input.role)) throw new UserError(400, `"role" must be one of ${USER_ROLES.join(', ')}`);
    result.role = input.role;
  }
  return result;
}

/** Kept exactly as typed (no trimming): spaces are allowed in a password. */
function validatePassword(password: unknown): string {
  const { min, max } = PASSWORD_LENGTH;
  if (typeof password !== 'string' || password.length < min || password.length > max) {
    throw new UserError(400, `"password" must be a string of ${min} to ${max} characters`);
  }
  return password;
}

function notFound(id: string): never {
  throw new UserError(404, `User ${id} not found`);
}

export const userService = new UserService(new UserRepository(database), passwordHasher);
