# SARIF Output Format Decision (Phase 0)

## Decision

CodeAtlas emits **SARIF v2.1.0** (OASIS standard) as a first-class change-impact
report format via `codeatlas impact --format sarif` and
`GET /v1/change-analysis/{id}/report?format=sarif`
(`src/codeatlas/delivery/sarif_report.py`, Phase 10).

## Rationale

- SARIF 2.1.0 is the de-facto interchange format consumed by GitHub code
  scanning, Azure DevOps, and most CI review surfaces — the intended downstream
  for CodeAtlas findings, without adopting GitHub *integration* (a deferred
  non-goal).
- It maps cleanly onto our `Finding` contract.

## Mapping (Finding → SARIF)

| CodeAtlas `Finding` | SARIF |
|---|---|
| `rule_id` | `result.ruleId` + `run.tool.driver.rules[].id` |
| `category` | rule `properties.category` |
| `severity` (critical/high/medium/low/info) | `result.level` (error/error/warning/note/note) + `properties.security-severity` |
| `title` | `result.message.text` (short) / rule `shortDescription` |
| `description` | rule `fullDescription` |
| `confidence`, `deterministic`, `derivation` | `result.properties` |
| evidence file + `start_line`/`end_line` | `physicalLocation.artifactLocation.uri` + `region` |
| `relation_path` | `codeFlows` / `result.properties.relationPath` |

## Constraints

- `tool.driver.name = "CodeAtlas"`, `version` from `codeatlas.__version__`.
- Artifact URIs are repo-relative, forward-slashed, original casing preserved.
- Only findings with **valid, validated** citations are emitted (citation
  validator wired into the report path — Phase 10 exit criteria).
- Output is validated against the SARIF 2.1.0 JSON schema in tests
  (Phase 10 build item).
