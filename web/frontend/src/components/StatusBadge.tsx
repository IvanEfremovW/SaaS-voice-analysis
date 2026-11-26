import type { CallStatus } from '#backend/modules/call/entity.ts';
import { STATUS_LABELS } from '#frontend/format.ts';

/** The status of a call; its colour comes from styles.css (.badge.FAILED etc). */
export function StatusBadge({ status }: { status: CallStatus }) {
  return <span className={`badge ${status}`}>{STATUS_LABELS[status]}</span>;
}
