# Bitrix24 mock

A mock of the part of the Bitrix24 REST API we need: getting the list of calls with their metadata, and downloading call recordings.
Responses follow the official Bitrix24 docs. The data is randomly generated.

## Run

```bash
npm start          # http://localhost:8024
npm run typecheck  # type-check only
```

Requires Node 24+. Node runs the `.ts` files directly, with no build step.

## How it works

To get a recording, you make three requests, the same way you would with real Bitrix24:

| # | Request | Returns | Bitrix24 docs |
|---|---|---|---|
| 1 | `GET /rest/voximplant.statistic.get` | A list of calls. A call with a recording has `RECORD_FILE_ID` set. | [voximplant.statistic.get](https://apidocs.bitrix24.com/api-reference/telephony/voximplant/voximplant-statistic-get.html) |
| 2 | `GET /rest/disk.file.get?id=<RECORD_FILE_ID>` | The recording's file info, including `DOWNLOAD_URL`. | [disk.file.get](https://apidocs.bitrix24.com/api-reference/disk/file/disk-file-get.html) |
| 3 | `GET <DOWNLOAD_URL>` (`/rest/download.json?token=...`) | The recording itself, a `.wav` file of noise. | [How to download files](https://apidocs.bitrix24.com/api-reference/files/how-to-download-files.html) |

Example:

```bash
# GET: the query string must be URL-encoded (FILTER[>=CALL_START_DATE] -> FILTER%5B%3E%3DCALL_START_DATE%5D)
curl "http://localhost:8024/rest/voximplant.statistic.get?FILTER%5B%3E%3DCALL_START_DATE%5D=2026-10-01&start=50"

# POST with a JSON body is accepted too, as in the Bitrix24 docs examples
curl -X POST -H "Content-Type: application/json" \
  -d '{"FILTER": {">=CALL_START_DATE": "2026-10-01"}, "start": 50}' \
  http://localhost:8024/rest/voximplant.statistic.get

curl "http://localhost:8024/rest/disk.file.get?id=9000"
```

### `voximplant.statistic.get`

- **Parameters.** All documented parameters are supported:
  - `FILTER`, with every documented field and operator (`=`, `!`, `>`, `>=`, `<`, `<=`, `><`, `%`, ...)
  - `SORT` and `ORDER`
  - `start` for paging, 50 calls per page
- **Generated data.** Every distinct `FILTER` gets its own random set of 10–200 calls, all of which match that filter. A filter can make the set smaller: `FILTER[ID]=[1,7]` returns at most 2 calls.
- **Paging.** The set is generated once per filter and then reused, so paging with `start` returns a consistent list.

### Things that differ from real Bitrix24

1. **No auth.** Two URL forms are accepted, same as Bitrix24:
   - `/rest/<method>`, used by OAuth apps
   - `/rest/<user_id>/<webhook_code>/<method>`, used by incoming webhooks

   A `.json` suffix on the method is optional. The mock never checks credentials, so any webhook code or `auth` token works, or none.
2. **Only the last 512 recording IDs are kept.**
   - Each `RECORD_FILE_ID` handed out by `voximplant.statistic.get` is kept in memory.
   - When there are more than 512, the oldest are dropped.
   - `disk.file.get` and the download return `ERROR_NOT_FOUND` for an ID that was dropped or never issued, and for any ID after a restart.
   - File details (name, length) are generated on the fly from the ID. The recording's length does not match the call's `CALL_DURATION`.
3. **Download links never expire,** and they aren't tied to the caller.

## Structure

```
src/
├── server.ts                    # parses the URL and passes the request to the method
├── voximplant.statistic.get/    # the call list: filter.ts, generator.ts, types.ts, rng.ts
├── disk.file.get/               # a recording's file info
├── rest.download.json/          # the recording download
└── utils/                       # code shared by several methods
                                 # (params, responses, time, recording IDs, wav generation)
mock_config.json                 # settings for the generated data
.env.defaults                    # app settings (PORT)
```

Each method lives in its own folder. Its handler is in `method.ts`.

Imports use the `#src/...` alias for `src/` (set in `package.json` → `imports`).

## Config: `mock_config.json`

This file holds every made-up value that shapes the generated data and isn't set by the Bitrix24 docs. Examples:
- how many calls a list contains (`MIN_TOTAL`, `MAX_TOTAL`)
- probabilities and weights
- ID ranges
- the timezone
- the 512-ID limit
- the recording's sample rate

Values are grouped by the file that reads them: `"<folder>" → "<file>" → "<VARIABLE>"`. For example, `MIN_TOTAL` is under `"voximplant.statistic.get"` → `"generator"`. A value used by several files goes at the top level.

Code reads the file with `import config from '#config' with { type: 'json' }`. TypeScript infers the types from the JSON itself, so `npm run typecheck` catches keys that were renamed in one place but not the other. Changes take effect after a restart.

`"voximplant.statistic.get" → "method" → "SEED"`: `null` gives new random data on every start. A number gives the same data every time.

## Environment and docker compose

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8024` | The port the server listens on. |

The default is in `.env.defaults`, which is committed to git and must not contain secrets. A `PORT` already set in the environment, for example by docker compose, takes precedence over the file. If you don't pass `PORT`, the server listens on `8024`.

```yaml
services:
  bitrix24-mock:
    build: ./mocks/bitrix24
    environment:
      PORT: 8024        # optional; 8024 is the default
    ports:
      - "8024:8024"     # host:container, the container side must equal PORT
```

Other containers reach the mock at `http://bitrix24-mock:8024`. Links in responses, such as `DOWNLOAD_URL`, are built from the request's `Host` header, so they work from the host and from inside the compose network.
