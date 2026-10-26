// Random but plausible call statistics records, shaped exactly like the
// voximplant.statistic.get response example in the Bitrix24 docs.

import config from '#config' with { type: 'json' };
import { addRecordFile } from '#src/utils/recordFiles.ts';
import { createRng, pick, randInt, randomDigits, randomHex, weighted } from './rng.ts';
import type { Rng } from './rng.ts';
import { formatDate, localHour } from '#src/utils/time.ts';
import { bounds, matchesAll, pinnedValues } from './filter.ts';
import type { CallRecord, Condition } from './types.ts';

const cfg = config['voximplant.statistic.get'].generator;

// {value: weight} objects from the config as [value, weight] pairs for weighted().
const CALL_TYPES = Object.entries(cfg.CALL_TYPE_WEIGHTS);
const INCOMING_CODES = Object.entries(cfg.INCOMING_CODE_WEIGHTS);
const OUTGOING_CODES = Object.entries(cfg.OUTGOING_CODE_WEIGHTS);
const CRM_TYPES = Object.entries(cfg.CRM_TYPE_WEIGHTS);
/** "603-S" -> "Decline self" is taken from the docs example; the other texts are made up. */
const FAILED_REASONS: Readonly<Record<string, string>> = cfg.FAILED_REASONS;

/** Safety limit for the generation loop, for filters that reject most candidates. */
const MAX_ATTEMPTS = 50_000;
const DAY_MS = 86_400_000;

type Client = { phone: string; crmType: string; crmId: string };

type Candidate = { record: CallRecord; hasRecording: boolean };

/**
 * Generates a selection of calls that satisfies all filter conditions.
 * 
 * The selection size is random in [MIN_TOTAL, MAX_TOTAL] unless the filter makes fewer calls possible
 * (e.g. FILTER[ID]=[1,7] can only match two records).
 */
export function generateCalls(conditions: readonly Condition[], seed: number, nowMs: number): CallRecord[] {
  const rng = createRng(seed);
  const target = randInt(rng, cfg.MIN_TOTAL, cfg.MAX_TOTAL);

  const dates = bounds(conditions, 'CALL_START_DATE');
  const hiMs = Math.min(dates.hi ?? nowMs, nowMs);
  const loMs = dates.lo ?? hiMs - cfg.DEFAULT_WINDOW_DAYS * DAY_MS;
  // A window entirely in the future (or inverted) cannot contain any calls.
  if (loMs > hiMs) return [];

  const clients: Client[] = Array.from({ length: randInt(rng, cfg.CLIENTS_COUNT.min, cfg.CLIENTS_COUNT.max) }, () => ({
    phone: cfg.CLIENT_PHONE.prefix + randomDigits(rng, cfg.CLIENT_PHONE.digits),
    crmType: weighted(rng, CRM_TYPES),
    crmId: String(randInt(rng, cfg.CRM_ENTITY_ID.min, cfg.CRM_ENTITY_ID.max)),
  }));

  const make = makeCandidateFactory(rng, conditions, clients, loMs, hiMs);
  const accepted: Candidate[] = [];

  const pinnedIds = pinnedValues(conditions, 'ID');
  if (pinnedIds) {
    // Explicit IDs: try each one a few times until a candidate passes the rest of the filter.
    const ids = [...new Set(pinnedIds.filter((v): v is number => typeof v === 'number' && Number.isInteger(v) && v > 0))];
    for (const id of ids.sort((a, b) => a - b).slice(0, cfg.MAX_TOTAL)) {
      for (let attempt = 0; attempt < 50; attempt++) {
        const candidate = make(id);
        if (matchesAll(candidate.record, conditions)) {
          accepted.push(candidate);
          break;
        }
      }
    }
  } else {
    const idBounds = bounds(conditions, 'ID');
    let id =
      idBounds.lo !== null
        ? Math.max(1, Math.ceil(idBounds.lo))
        : idBounds.hi !== null
          ? Math.max(1, Math.floor(idBounds.hi) - randInt(rng, 300, 600))
          : randInt(rng, cfg.FIRST_CALL_ID.min, cfg.FIRST_CALL_ID.max);
    for (let attempt = 0; attempt < MAX_ATTEMPTS && accepted.length < target; attempt++) {
      if (idBounds.hi !== null && id > idBounds.hi) break;
      const candidate = make(id);
      if (matchesAll(candidate.record, conditions)) accepted.push(candidate);
      id += randInt(rng, 1, 3);
    }
  }

  // IDs grow with time in a real portal: hand the same set of IDs out again in date order.
  // Every condition is per field, so permuting IDs between matching records keeps them matching.
  const ids = accepted.map((c) => Number(c.record.ID)).sort((a, b) => a - b);
  accepted.sort((a, b) => Date.parse(a.record.CALL_START_DATE) - Date.parse(b.record.CALL_START_DATE));
  accepted.forEach((c, i) => {
    c.record.ID = String(ids[i]);
    if (c.hasRecording) c.record.RECORD_FILE_ID = addRecordFile();
  });

  return accepted.map((c) => c.record);
}

function makeCandidateFactory(
  rng: Rng,
  conditions: readonly Condition[],
  clients: readonly Client[],
  loMs: number,
  hiMs: number,
): (id: number) => Candidate {
  // Fields pinned by an "=" filter take one of the allowed values, so most candidates
  // pass the filter on the first try. Everything else is checked by matchesAll().
  const choose = (field: string, fallback: () => string): string => {
    const values = pinnedValues(conditions, field);
    if (!values || values.length === 0) return fallback();
    const v = pick(rng, values);
    return v === null ? '' : String(v);
  };
  const chooseNullable = (field: string, fallback: () => string | null): string | null => {
    const values = pinnedValues(conditions, field);
    if (!values || values.length === 0) return fallback();
    const v = pick(rng, values);
    return v === null ? null : String(v);
  };

  const pinnedDates = pinnedValues(conditions, 'CALL_START_DATE');
  const sampleStart = (): number => {
    if (pinnedDates && pinnedDates.length > 0) {
      const v = pick(rng, pinnedDates);
      if (typeof v === 'number') return v;
    }
    let t = loMs + rng() * (hiMs - loMs);
    // Most calls happen during working hours.
    const { from, to, probability } = cfg.WORKING_HOURS;
    const hour = localHour(t);
    if (rng() < probability && (hour < from || hour >= to)) {
      const shifted = t + (randInt(rng, from, to - 1) - hour) * 3_600_000;
      if (shifted >= loMs && shifted <= hiMs) t = shifted;
    }
    return Math.max(loMs, Math.floor(t / 1000) * 1000);
  };

  const talkDuration = (): number => {
    const range = weighted(rng, cfg.TALK_DURATION_SEC.map((r) => [r, r.weight] as const));
    return randInt(rng, range.min, range.max);
  };

  return (id) => {
    const app = pick(rng, cfg.REST_APPS);
    const external = chooseNullable('REST_APP_ID', () => (rng() < cfg.EXTERNAL_CALL_PROBABILITY ? app.id : null)) !== null;

    const callType = choose('CALL_TYPE', () => weighted(rng, CALL_TYPES));
    const incoming = callType === '2' || callType === '3';
    const code = choose('CALL_FAILED_CODE', () => weighted(rng, incoming ? INCOMING_CODES : OUTGOING_CODES));
    const success = code === '200';
    const duration = Number(choose('CALL_DURATION', () => String(success ? talkDuration() : 0)));
    const hasRecording = success && duration >= 5 && rng() < cfg.RECORDING_PROBABILITY;

    const startMs = sampleStart();
    const startUnix = Math.floor(startMs / 1000);
    const client = pick(rng, clients);
    const sessionId = external ? null : randomDigits(rng, 10);

    const minutes = Math.ceil(duration / 60);
    const cost = !external && !incoming && success ? minutes * cfg.COST_PER_MINUTE : 0;

    const record: CallRecord = {
      ID: String(id),
      PORTAL_USER_ID: choose('PORTAL_USER_ID', () => pick(rng, cfg.PORTAL_USERS)),
      PORTAL_NUMBER: choose('PORTAL_NUMBER', () => (external ? app.line : pick(rng, cfg.VOXIMPLANT_LINES))),
      // The docs example has "+1906..." for a Voximplant call and "1906..." for an external one.
      PHONE_NUMBER: choose('PHONE_NUMBER', () => (external ? client.phone : `+${client.phone}`)),
      CALL_ID: choose('CALL_ID', () =>
        external
          ? `externalCall.${randomHex(rng, 32)}.${startUnix}`
          : `${randomHex(rng, 16).toUpperCase()}.${startUnix}.${randomDigits(rng, 8)}`,
      ),
      EXTERNAL_CALL_ID: null,
      CALL_CATEGORY: choose('CALL_CATEGORY', () => 'external'),
      CALL_LOG: external ? null : voximplantLogUrl(rng, startMs, sessionId ?? ''),
      CALL_DURATION: String(duration),
      CALL_START_DATE: formatDate(startMs),
      // Both docs examples leave this empty (even the one with a recording), so the real link to the
      // audio goes through RECORD_FILE_ID -> disk.file.get.
      CALL_RECORD_URL: external ? null : '',
      CALL_VOTE: chooseNullable('CALL_VOTE', () => (success && rng() < cfg.VOTE_PROBABILITY ? String(randInt(rng, 1, 5)) : null)),
      COST: cost.toFixed(4),
      COST_CURRENCY: choose('COST_CURRENCY', () => (external ? '' : cfg.COST_CURRENCY)),
      CALL_FAILED_CODE: code,
      CALL_FAILED_REASON: FAILED_REASONS[code] ?? '',
      CRM_ENTITY_TYPE: choose('CRM_ENTITY_TYPE', () => client.crmType),
      CRM_ENTITY_ID: choose('CRM_ENTITY_ID', () => client.crmId),
      CRM_ACTIVITY_ID: choose('CRM_ACTIVITY_ID', () => String(randInt(rng, cfg.CRM_ACTIVITY_ID.min, cfg.CRM_ACTIVITY_ID.max))),
      REST_APP_ID: external ? app.id : null,
      REST_APP_NAME: external ? app.name : null,
      TRANSCRIPT_ID: hasRecording && rng() < cfg.TRANSCRIPT_PROBABILITY ? String(randInt(rng, cfg.TRANSCRIPT_ID.min, cfg.TRANSCRIPT_ID.max)) : null,
      TRANSCRIPT_PENDING: choose('TRANSCRIPT_PENDING', () => 'N'),
      SESSION_ID: sessionId,
      REDIAL_ATTEMPT: callType === '4' ? String(randInt(rng, 1, 3)) : null,
      COMMENT: rng() < cfg.COMMENT_PROBABILITY ? pick(rng, cfg.COMMENTS) : null,
      RECORD_DURATION: hasRecording ? String(duration) : null,
      RECORD_FILE_ID: null, // assigned once the record is accepted
      CALL_TYPE: callType,
    };
    return { record, hasRecording };
  };
}

function voximplantLogUrl(rng: Rng, startMs: number, sessionId: string): string {
  const [year, month, day] = formatDate(startMs).slice(0, 10).split('-');
  const name = Buffer.from(randomHex(rng, 48)).toString('base64url');
  return `${cfg.CALL_LOG_URL_BASE}/${year}/${month}/${day}/${name}?sessionid=${sessionId}`;
}
