import { database } from '#app/infrastructure/database.ts';
import { USER_ROLES, UserError } from './entity.ts';
import type { CreateUserInput, UpdateUserInput, User } from './entity.ts';
import { UserRepository } from './repository.ts';

export class UserService {
  #users: UserRepository;

  constructor(users: UserRepository) {
    this.#users = users;
  }

  async create(input: CreateUserInput): Promise<User> {
    return this.#users.create(validate(input, true) as CreateUserInput);
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

  async delete(id: string): Promise<void> {
    if (!(await this.#users.delete(id))) notFound(id);
  }
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Checks the input at runtime (it comes from JSON) and returns only the known fields. */
function validate(input: UpdateUserInput, isCreate: boolean): UpdateUserInput {
  if (typeof input !== 'object' || input === null) throw new UserError(400, 'Body must be a JSON object');
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

function notFound(id: string): never {
  throw new UserError(404, `User ${id} not found`);
}

export const userService = new UserService(new UserRepository(database));
