# invariant_ingestion

Fetches CIS benchmark PDFs, parses them into recommendations, and
normalizes those into controls. No Postgres access -- returns structured
data; `invariant_api` persists it.

Extracted from the `Invariant-Security/Invariant` monolith
(`src/invariant/{collector,extractor,normalizer,source}/`) as part of its
split into `invariant_*` services. Parsing/normalization logic is ported
unchanged -- only the wiring around it (no more direct Postgres writes,
exposed over HTTP instead of the `invariant fetch`/`extract`/
`import_document` CLI commands) changed.

## Endpoints

- `GET /healthz`
- `POST /ingestion/fetch/{document}` -- downloads the latest PDF for a
  known document (`source.KNOWN_CIS_DOCUMENTS`), saves it to `data/raw/`.
- `POST /ingestion/extract/{document}` -- parses the most recently fetched
  raw artifact for that document into recommendations.
- `POST /ingestion/normalize` -- normalizes a list of extracted items into
  controls.

## Development

```bash
pip install -e ".[dev]"
playwright install --with-deps chromium   # only needed for discover_benchmarks()
pytest tests/ -q                          # unit tests, no network needed
pytest tests/ -q -m integration           # hits real cisecurity.org
uvicorn invariant_ingestion.api:app --reload
```
