// Bitrix24 responses read by client.ts (only the fields the module uses).

export type BitrixCall = {
  CALL_ID: string;
  PORTAL_USER_ID: string;
  PHONE_NUMBER: string;
  /** 1 outgoing, 2 incoming, 3 incoming with redirection, 4 callback, 5 informational. */
  CALL_TYPE: string;
  CALL_START_DATE: string;
  CALL_DURATION: string;
  /** "200" = successful call. */
  CALL_FAILED_CODE: string;
  RECORD_FILE_ID: number | null;
};

export type BitrixDiskFile = {
  NAME: string;
  DOWNLOAD_URL: string;
};
