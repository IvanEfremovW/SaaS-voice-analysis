// What the backend gives to the pages. The frontend imports these types (types only, never code).

export type UserRole = 'USER' | 'ADMIN';

export type User = {
  id: string;
  name: string;
  email: string;
  role: UserRole;
};
