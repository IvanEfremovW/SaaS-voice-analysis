import { redirect } from 'react-router';
import type { RouteObject } from 'react-router';
import { HttpError } from '#frontend/api.ts';
import { currentUserLoader } from '#frontend/currentUser.ts';
import { ErrorPage } from '#frontend/layout/ErrorPage.tsx';
import { Layout } from '#frontend/layout/Layout.tsx';
import { PageLoader } from '#frontend/layout/PageLoader.tsx';
import { callRoute } from '#frontend/pages/call/route.ts';
import { callsRoute } from '#frontend/pages/calls/route.ts';
import { userRoute } from '#frontend/pages/user/route.ts';
import { usersRoute } from '#frontend/pages/users/route.ts';

// All pages of the app. Each page lives in pages/<name>/, next to its route.ts (URL, data to load, component).
export const routes: RouteObject[] = [
  {
    // The frame shared by all pages (the sidebar); the current page is drawn inside it, at <Outlet />.
    id: 'root',
    loader: currentUserLoader,
    Component: Layout,
    // Drawn instead of the frame if even the frame cannot load, e.g. there is no current user.
    ErrorBoundary: ErrorPage,
    HydrateFallback: PageLoader,
    children: [
      {
        // If a page fails to load, ErrorPage is drawn in its place, still inside the frame.
        ErrorBoundary: ErrorPage,
        children: [
          // The loader always redirects, so the empty component is never drawn.
          { path: '/', loader: () => redirect('/calls'), Component: () => null },
          callsRoute,
          callRoute,
          userRoute,
          usersRoute,
          {
            path: '*',
            loader: () => {
              throw new HttpError(404, 'Нет такой страницы');
            },
          },
        ],
      },
    ],
  },
];
