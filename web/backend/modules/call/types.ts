// Answers of data_provider (only the fields the backend uses).

import type { CallDirection, CallStatus } from './entity.ts';

export type ProviderCall = {
  id: string;
  userId: string;
  clientPhone: string;
  direction: CallDirection;
  startedAt: string;
  durationSec: number;
  fileId: string;
  status: { value: CallStatus; error: string | null };
};

export type ProviderCallFilter = {
  userId?: string | undefined;
  from?: string | undefined;
  to?: string | undefined;
};

export type ProviderFile = {
  id: string;
  name: string;
  sizeBytes: number;
};

export type ProviderTranscription = {
  id: string;
  callId: string;
  fileId: string;
  createdAt: string;
};
