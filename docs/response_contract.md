# Response Contract (Phase 0)

The canonical response contract (Blueprint §7.6) is implemented as Pydantic v2
models in [`src/codeatlas/contracts.py`](../src/codeatlas/contracts.py) and is
identical across CLI, MCP, REST, and JSON reports.

Top-level model: `QueryResponse`

```jsonc
{
  "answer": "The payment capture flow is used by two API handlers and one retry worker.",
  "confidence": 0.87,
  "intent": "IMPACT_ANALYSIS",
  "scope": {
    "repository_id": "repo_001",
    "snapshot_id": "snapshot_019",
    "branch": "feature/idempotency",
    "commit_sha": "abc123"
  },
  "claims": [
    {
      "text": "The partner payment endpoint calls PaymentService.capture.",
      "confidence": 0.98,
      "evidence_ids": ["evidence_01"]
    }
  ],
  "evidence": [
    {
      "id": "evidence_01",
      "snapshot_id": "snapshot_019",
      "kind": "code",
      "file_path": "src/api/partner_payments.py",
      "symbol": "capture_partner_payment",
      "start_line": 42,
      "end_line": 68,
      "relation_path": ["capture_partner_payment", "CALLS", "PaymentService.capture"],
      "confidence": 0.98,
      "derivation": "static_resolved"
    }
  ],
  "findings": [],
  "warnings": ["One dynamic call could not be resolved."]
}
```

## Guarantees

- Every claim references ≥1 evidence ID; every evidence item carries snapshot,
  file, lines, confidence, and derivation.
- All evidence in one response belongs to `scope.snapshot_id` unless the query is
  explicitly historical (snapshot consistency, CLAUDE.md §2.7).
- Confidence bands (Blueprint §7.7): high ≥ 0.80, medium ≥ 0.55, low < 0.55.
- Models are `extra="forbid"` and frozen — unknown fields are a contract error.
