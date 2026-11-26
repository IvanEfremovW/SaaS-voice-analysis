import type { ActionFunctionArgs, LoaderFunctionArgs, RouteObject } from 'react-router';
import type { CallDetails } from '#backend/modules/call/entity.ts';
import { HttpError, api } from '#frontend/api.ts';
import { CallPage } from './CallPage.tsx';

/** Gets the call whose id is in the URL (/call/:id). */
export async function callLoader({ params }: LoaderFunctionArgs) {
  return (await api.get<{ call: CallDetails }>(`/calls/${encodeURIComponent(params.id ?? '')}`)).call;
}

/**
 * Runs when the page's <Form method="post"> is sent: asks for a new transcription.
 * After an action React Router runs the loader again, so the page shows the new state.
 */
export async function callAction({ params }: ActionFunctionArgs) {
  try {
    await api.post(`/calls/${encodeURIComponent(params.id ?? '')}/transcription`);
    return { error: null };
  } catch (err) {
    // Shown next to the button instead of replacing the page with ErrorPage.
    if (err instanceof HttpError) return { error: err.message };
    throw err;
  }
}

export const callRoute: RouteObject = {
  path: '/call/:id',
  loader: callLoader,
  action: callAction,
  Component: CallPage,
};
