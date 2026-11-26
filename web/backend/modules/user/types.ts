// Answers of data_provider (only the fields the backend uses).

import type { UserRole } from './entity.ts';

export type ProviderUser = {
  id: string;
  name: string;
  email: string;
  role: UserRole;
};
