import type { DatabaseClient } from '#app/infrastructure/database.ts';
import type { User as UserRow } from '#app/generated/prisma/client.ts';
import { UserError } from './entity.ts';
import type { UpdateUserInput, User } from './entity.ts';
import type { NewUser, UserWithPasswordHash } from './types.ts';

export class UserRepository {
  #db: DatabaseClient;

  constructor(db: DatabaseClient) {
    this.#db = db;
  }

  async create({ passwordHash, ...fields }: NewUser): Promise<User> {
    try {
      return toUser(await this.#db.user.create({ data: { ...fields, password_hash: passwordHash } }));
    } catch (err) {
      throw translate(err);
    }
  }

  async findById(id: string): Promise<User | null> {
    const row = await this.#db.user.findUnique({ where: { id } });
    return row && toUser(row);
  }

  /** The user with their password hash, to check a password. */
  async findWithPasswordHash(email: string): Promise<UserWithPasswordHash | null> {
    const row = await this.#db.user.findUnique({ where: { email } });
    return row && { user: toUser(row), passwordHash: row.password_hash };
  }

  async list(): Promise<User[]> {
    const rows = await this.#db.user.findMany({ orderBy: { created_at: 'asc' } });
    return rows.map(toUser);
  }

  /** Null if there is no such user. */
  async update(id: string, input: UpdateUserInput): Promise<User | null> {
    try {
      return toUser(await this.#db.user.update({ where: { id }, data: input }));
    } catch (err) {
      if (errorCode(err) === 'P2025') return null;
      throw translate(err);
    }
  }

  /** False if there is no such user. */
  async setPasswordHash(id: string, passwordHash: string): Promise<boolean> {
    try {
      await this.#db.user.update({ where: { id }, data: { password_hash: passwordHash } });
      return true;
    } catch (err) {
      if (errorCode(err) === 'P2025') return false;
      throw err;
    }
  }

  /** False if there is no such user. */
  async delete(id: string): Promise<boolean> {
    try {
      await this.#db.user.delete({ where: { id } });
      return true;
    } catch (err) {
      if (errorCode(err) === 'P2025') return false;
      throw translate(err);
    }
  }
}

// Leaves out password_hash: a User goes to other services as it is.
function toUser(row: UserRow): User {
  return {
    id: row.id,
    name: row.name,
    email: row.email,
    role: row.role,
    createdAt: row.created_at.toISOString(),
    updatedAt: row.updated_at.toISOString(),
  };
}

// https://www.prisma.io/docs/orm/reference/error-reference
function errorCode(err: unknown): string | undefined {
  return (err as { code?: string }).code;
}

function translate(err: unknown): unknown {
  switch (errorCode(err)) {
    case 'P2002':
      return new UserError(409, 'A user with this email already exists');
    case 'P2003':
      return new UserError(409, 'The user still has calls');
    default:
      return err;
  }
}
