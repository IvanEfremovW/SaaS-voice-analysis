export const USER_ROLES = ['USER', 'ADMIN'] as const;
export type UserRole = (typeof USER_ROLES)[number];

/** The user never includes the password or its hash. */
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
  /** Only its hash is stored. */
  password: string;
  /** USER if omitted */
  role?: UserRole;
};

/** The password is changed separately, with PUT /users/:id/password. */
export type UpdateUserInput = Partial<Omit<CreateUserInput, 'password'>>;

export type CheckPasswordInput = {
  email: string;
  password: string;
};

/** An error with the HTTP status the API answers with. */
export class UserError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
