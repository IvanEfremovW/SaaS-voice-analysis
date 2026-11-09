// Types of voximplant.statistic.get.

/** One call, field order and value types as in the docs response example. */
export type CallRecord = {
  ID: string;
  PORTAL_USER_ID: string;
  PORTAL_NUMBER: string;
  PHONE_NUMBER: string;
  CALL_ID: string;
  EXTERNAL_CALL_ID: string | null;
  CALL_CATEGORY: string;
  CALL_LOG: string | null;
  CALL_DURATION: string;
  CALL_START_DATE: string;
  CALL_RECORD_URL: string | null;
  CALL_VOTE: string | null;
  COST: string;
  COST_CURRENCY: string;
  CALL_FAILED_CODE: string;
  CALL_FAILED_REASON: string;
  CRM_ENTITY_TYPE: string;
  CRM_ENTITY_ID: string;
  CRM_ACTIVITY_ID: string;
  REST_APP_ID: string | null;
  REST_APP_NAME: string | null;
  TRANSCRIPT_ID: string | null;
  TRANSCRIPT_PENDING: string;
  SESSION_ID: string | null;
  REDIAL_ATTEMPT: string | null;
  COMMENT: string | null;
  RECORD_DURATION: string | null;
  RECORD_FILE_ID: number | null;
  CALL_TYPE: string;
};

export type FieldType = 'int' | 'double' | 'string' | 'datetime';

export type Operator = '!><' | '><' | '>=' | '<=' | '!=' | '!%' | '!' | '>' | '<' | '=' | '%' | '?';

/**
 * A filter value converted to the field's type: number for int/double, epoch ms for datetime,
 * string for strings, null for "empty" ("" or null).
 */
export type FilterValue = number | string | null;

/** One FILTER entry, e.g. {">=CALL_START_DATE": "2025-01-01"} -> {field, op: ">=", values: [ms]}. */
export type Condition = {
  field: string;
  op: Operator;
  values: FilterValue[];
};

export type Order = 'ASC' | 'DESC';
