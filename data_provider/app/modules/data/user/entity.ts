export const USER_ROLES = ['USER', 'ADMIN'] as const;
export type UserRole = (typeof USER_ROLES)[number];

export type User = {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  /** ISO-8601 */
  createdAt: string;
  updatedAt: string;
};

export type CreateUserInput = {
  name: string;
  email: string;
  /** USER if omitted */
  role?: UserRole;
};

export type UpdateUserInput = Partial<CreateUserInput>;

/** An error with the HTTP status the API answers with. */
export class UserError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
