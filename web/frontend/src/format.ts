import type { CallDirection, CallStatus } from '#backend/modules/call/entity.ts';
import type { UserRole } from '#backend/modules/user/entity.ts';

export const STATUS_LABELS: Record<CallStatus, string> = {
  UPLOADED: 'Загружен',
  TRANSCRIBING: 'Транскрибируется',
  TRANSCRIBED: 'Транскрибирован',
  ANALYZING: 'Анализируется',
  ANALYZED: 'Проанализирован',
  FAILED: 'Ошибка',
};

export const DIRECTION_LABELS: Record<CallDirection, string> = {
  INCOMING: 'Входящий',
  OUTGOING: 'Исходящий',
};

export const ROLE_LABELS: Record<UserRole, string> = {
  USER: 'Сотрудник',
  ADMIN: 'Администратор',
};

/** "01.11.2026, 09:00" in the browser's time zone */
export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
}

/** 95 -> "1:35" */
export function formatDuration(totalSec: number): string {
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return `${min}:${String(sec).padStart(2, '0')}`;
}

/** 2048 -> "2 КБ" */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}
