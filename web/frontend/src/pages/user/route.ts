import type { RouteObject } from 'react-router';
import { UserPage } from './UserPage.tsx';

// No loader: the page shows the logged-in user, whom the root route has already loaded.
export const userRoute: RouteObject = {
  path: '/user',
  Component: UserPage,
};
