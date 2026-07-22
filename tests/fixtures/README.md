# Evaluation Fixtures

These directories are **evaluation data**, not part of CodeAtlas's own test
suite. pytest is configured to ignore `tests/fixtures` entirely
(`--ignore=tests/fixtures`), so the `test_*.py` files inside the fixtures are
never collected as CodeAtlas tests. They exist so the parser/impact engine has
realistic test code to link to.

| Fixture | Languages | Exercises |
|---|---|---|
| `python_repo/` | Python, Markdown, TOML | classes, routes, tests, config, ADR, call graph |
| `typescript_repo/` | TypeScript, JSON | ESM imports, classes, route, interfaces/enums, jest test |
| `markdown_repo/` | Markdown | headings, code blocks, tables, config-key & symbol references, ADR |
| `mixed_repo/` | Python, TypeScript, YAML/JSON/TOML | multi-language scanning & classification |

Benchmark truth that references these fixtures lives in
[`../evaluation/`](../evaluation/). The benchmark questions and change cases are
authored by hand — **no LLM-generated ground truth** (Phase 0 exit criterion).
