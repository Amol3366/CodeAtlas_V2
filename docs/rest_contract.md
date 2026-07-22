# REST API Contract (Phase 0 draft)

FastAPI app (`apps/api/main.py`), local-only, all routes under `/v1`. Responses
use the schemas in `src/codeatlas/contracts.py`. Routes mirror Blueprint §12.

## Repositories
```text
POST   /v1/repositories                                  # register
GET    /v1/repositories
GET    /v1/repositories/{repository_id}
DELETE /v1/repositories/{repository_id}                  # unregister; never deletes source
POST   /v1/repositories/{repository_id}/index
GET    /v1/repositories/{repository_id}/status
GET    /v1/repositories/{repository_id}/files
GET    /v1/repositories/{repository_id}/diagnostics
GET    /v1/repositories/{repository_id}/snapshots/active
GET    /v1/repositories/{repository_id}/semantic-status   # Phase 12
```

## Query
```text
POST   /v1/query
POST   /v1/query/stream
GET    /v1/evidence/{evidence_id}
GET    /v1/files/{file_id}
GET    /v1/symbols/{symbol_id}
GET    /v1/symbols/{symbol_id}/relations
```

## Search
```text
GET    /v1/search/files
GET    /v1/search/symbols
GET    /v1/search/text
```

## Change analysis
```text
POST   /v1/change-analysis/working-tree
POST   /v1/change-analysis/commits
GET    /v1/change-analysis/{analysis_id}
GET    /v1/change-analysis/{analysis_id}/report          # ?format=json|markdown|sarif
```

## Settings & models (opt-in providers, Phase 12-13)
```text
GET    /v1/settings
PATCH  /v1/settings
GET    /v1/models
POST   /v1/models/test
POST   /v1/models/embedding-migrations
GET    /v1/models/embedding-migrations/{migration_id}
POST   /v1/models/embedding-migrations/{migration_id}/activate
```

## Error contract

HTTP problem responses carry a stable `error_code` derived from
`domain/errors.py` (e.g. `PATH_SECURITY`, `SNAPSHOT_NOT_READY`,
`BUDGET_EXHAUSTED`) plus a human `message`. No route requires an external
provider for core operation.
