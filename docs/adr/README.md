# Architecture Decision Records

ADRs capture decisions that affect product scope, privacy, trust, compatibility,
security, persistence, deployment, or an established public contract.

## Workflow

1. Copy `0000-template.md` to the next four-digit number and a short slug.
2. Set status to `proposed`; describe context, decision, alternatives,
   consequences, migration/rollback, security/privacy effects, and approval.
3. Link supporting measurements or discovery evidence.
4. Obtain explicit user/product approval for decisions listed in `AGENTS.md`
   Section 25.
5. Set status to `accepted` only after approval. Implementation plans may then
   depend on it.
6. Never edit an accepted decision to change its meaning. Add a new ADR with
   status `supersedes ADR-NNNN`.

ADR timestamps use UTC dates. Rejected and superseded records remain for audit.

## Accepted records

| ADR | Decision | Phase |
| --- | --- | --- |
| [0001](0001-local-deterministic-modular-monolith.md) | Local-first deterministic modular monolith; SQLite as the system of record | 0 |
| [0002](0002-phase1-storage-and-migration-mechanism.md) | Storage layout and the explicit forward-only migration mechanism | 1 |
| [0003](0003-evidence-granularity.md) | Evidence granularity; the gate is measured on containing evidence, and the corpus is never edited to fit the engine | 3 |
| [0004](0004-relation-model-and-contract-additions.md) | Relation model, derivation classes, and the additive contract entries | 3 |
| [0005](0005-change-assurance-engine-design.md) | Change-assurance engine: state views, impact orientation, finding rules, risk ordering | 4 |
| [0006](0006-web-application-design.md) | Web application: persistence, streaming, sanitization, and evidence presentation | 5 |
| [0007](0007-freshness-and-hardening-design.md) | The watcher is a trigger, never an authority; recovery, backup, and packaging decisions | 6 |
| [0008](0008-accept-then-stream-message-submission.md) | Accept-then-stream message submission; `contract_version` 1.0 → 1.1 | 6 |
| [0009](0009-measured-semantic-uplift.md) | Optional semantic layer admitted: provider-neutral embeddings, LanceDB base/delta with SQLite membership authoritative, per-repository privacy governance, shadow migration, measurement-admitted rerank/explanation | 7 |
| [0010](0010-repository-scoped-embedding-namespaces.md) | Which similarity space answers is a per-repository pointer, not a global active flag; migration `0012` drops the one-active index and backfills existing databases | 7 (post-gate) |
| [0011](0011-configurable-embedding-models.md) | Embedding model identity is configurable through `.env`; namespace derivation keeps it safe, and a custom OpenAI model must declare its width | 7 (post-gate) |
| [0012](0012-governed-answer-provider-policy.md) | Answer generation writes prose over untouched claims and evidence; local `llama3.2:3b` is primary, the default is off, and the feature ships available rather than admitted | 7 (post-gate) |
| [0013](0013-ephemeral-session-mode.md) | Ephemeral sessions are opt-in and never the default; one injected database path makes indexing, embeddings, and storage fresh per run, and §8.2's persistence requirement is scoped to default mode | none (post-gate) |
| [0014](0014-per-repository-embedding-model.md) | The embedding model is a per-repository decision for the local provider; migration `0014` stores it, precedence is policy → `.env` → default, and a candidate model's width is measured rather than declared | none (post-gate) |
| [0015](0015-frontend-credential-entry.md) | The OpenAI API key is entered in Settings and stored in the Windows Credential Manager, machine-wide, precedence store → `.env`; no response carries the value or any part of it, and the resolved key is never published to `os.environ` | none (post-gate) |
| [0016](0016-derivation-tiered-test-edges.md) | `TESTS` is derivation-tiered — direct edges stay `high_confidence_heuristic`, fixture- and helper-mediated edges are `low_confidence_heuristic`; `CONSUMES_FIXTURE` is stored and citable but excluded from impact expansion, and a weak edge explains a `test_gaps` entry without ever closing it | none (post-gate) |
| [0017](0017-evaluation-fixture-gate-correction.md) | `SUPPORTED_FIXTURES` had been frozen since Phase 1, scoring 16 of 39 query cases as misses the engine never saw; widening it to every fixture but `malicious_unsupported` moved `exact_symbol_resolution` 0.3846 → 0.6154 and `abstention_correctness` 0.5250 → 0.7500, regenerating the two live baselines while Phase 1–2 stay frozen as history — **corrected by ADR-0018** | none (post-gate) |
| [0018](0018-graph-query-subject.md) | A graph case declares `query_subject`, because `expected_symbols` is the answer and the subject is not in it; six cases declare it, the subject named is the one the question asks rather than the one the engine answers, and the module-symbol ranking and `related_tests` method-resolution findings it exposes are deferred rather than bundled | none (post-gate) |
| [0019](0019-export-evidence-labelling.md) | Evidence is labelled with the symbol whose definition its cited range covers — `EXPORTS` cites the exported symbol, every other kind cites a reference site inside the source; fixes an evidence object that named one symbol and showed another, with the `IMPORTS` counterpart pinned so the fix cannot flip it too | none (post-gate) |
| [0020](0020-relations-in-every-graph-answer.md) | Every graph answer populates `relation_paths`, not just `trace` — the traversal already computed them and `_respond` discarded them, leaving an MCP client with prose and no machine-readable statement of what relates to what; also revives `relation_path_correctness`, a metric structurally stuck at 0.0000 since Phase 3 | none (post-gate) |
| [0021](0021-method-level-test-edges.md) | A method is never imported, so no method could ever carry a `TESTS` edge — import-and-call now applies at the right granularity (imported **class**, resolved call to its method, `static_resolved`), fixing a false `test_gaps` entry on the most common shape of Python test; the owner must be a class, never a module, a constraint the ADR-0016 invariant corpus caught | none (post-gate) |
| [0022](0022-corpus-line-endings.md) | One corpus variant file held CRLF in the working tree, so every line of it differed and all five of its functions reported as changed against a case declaring one; `baseline-phase-7` encoded that drift and exited 5 on a correctly-checked-out tree. Restoring the file takes `changed_symbol_precision` 0.2000 → 1.0000, leaving Phase 7 with three unmet targets rather than four | none (post-gate) |
| [0023](0023-target-profiles.md) | A dataset declares a `target_profile`, so a 14-case conceptual corpus is no longer held to a 0.98 top-1 rule written for exact symbol lookup; `exact_symbol_resolution` is scoped to symbol-shaped intents (1.0000) with a new **failing** `lexical_resolution` gate (0.3000) as the condition that keeps the scoping honest; the evidence gate reads `containing_evidence_rate` with its 1.0 threshold unchanged | none (post-gate) |
| [0024](0024-unmeasured-is-not-wrong.md) | The adapter promised that "not implemented" and "answered wrongly" stay different facts; the scorer blurred them, so cases on a deliberately excluded fixture counted as misses and put an unreachable 0.80 ceiling under a 0.90 gate. `QueryPrediction.measured` carries the distinction and unmeasured cases leave every accuracy aggregate — including `abstention_correctness`, which was crediting the engine for decisions it never made | none (post-gate) |
| [0025](0025-nested-configuration-keys.md) | `_nested_paths` computed `service.port` and friends and then flattened them into a display string, so a nested key was searchable prose but not an addressable symbol and a config lookup could only answer the parent; each leaf now cites the line that sets it, with a text-matched line that falls back to the parent's range rather than being guessed | none (post-gate) |
| [0026](0026-exact-match-ranking.md) | Ranking was pure BM25, so a short parent block out-scored the leaf a caller asked for by name while a longer one did not — whether you got your key or its parent depended on the parent's length; an exact `qualified_name` match is now promoted within the returned window, as a stable partition that leaves every other query's order untouched | none (post-gate) |

| [0027](0027-containing-evidence-recall.md) | `primary_evidence_recall_at_10` compared line ranges for exact equality, so a citation one line longer than the gold range scored as never found — four of Phase 7's five misses return the right evidence at ranks 1, 1, 2 and 4. ADR-0003's containment predicate now backs a `containing_evidence_recall_at_10` that takes the gate at an unchanged 0.90 threshold, with the exact-match number retained so no historical figure changes meaning. **No engine behaviour changed** | none (post-gate) |

| [0028](0028-rank-fusion.md) | Fusion appended semantic candidates after all deterministic evidence and dropped any already cited, so a chunk both channels found kept its lexical position — the semantic channel ranked s007's answer 8th and s003's 1st while the fused answer buried them at 16th and 5th, and **two separately-recorded engine defects turned out to be one fusion defect**. Reciprocal-rank fusion over both channels, ranks only and never scores; Recall@10 1.0000 and MRR 0.4429 → 0.6875 with evidence rates unchanged, the signature of a pure reorder | none (post-gate) |

| [0029](0029-memberless-container-chunks.md) | A class chunk is an outline naming its members, which is right until the class has no member *symbols* — an enum's values are assignments, so `OrderStatus` was indexed as `class OrderStatus(Enum):` and nothing else, with `DRAFT`/`PLACED`/`SHIPPED`/`CANCELLED` and its docstring absent from the index entirely. A container with no members is a leaf and carries its body; `CHUNKER_VERSION` 1.0.0 → 1.1.0, its first move since Phase 2, so every snapshot must be re-indexed | none (post-gate) |

| [0030](0030-conceptual-answers-at-module-granularity.md) | s001's last miss is not a defect: the module docstring "Keeping two customers from being sold the same unit" paraphrases the question, so both channels rank the module first and are right to, while the corpus declares the method that implements it. **Nothing is changed** — the coarse-chunk penalty that would promote the method also demotes the chunk currently providing the rank-1 containment hit, so it trades an evidence hit for a symbol hit and needs corpus-wide measurement, not one case | none (post-gate) |

| [0031](0031-document-section-naming.md) | The corpus used two conventions for naming a markdown section — q019 declared `README.Health` while q027/q031 declared bare headings and extraction emits bare headings everywhere. Because `expected_symbols[0]` is **the query the harness issues**, q019 was asking for a symbol nothing can produce and the engine's correct abstention was scored as a miss. Bare heading is now the single rule; `lexical_resolution` 0.8750 → 1.0000 and `abstention_correctness` → 1.0000, from one line — the leverage ADR-0003 restrains, justified by the corpus contradicting itself rather than by the number | none (post-gate) |

| [0032](0032-lexical-resolution-threshold.md) | `lexical_resolution` scores **eight** cases (two of ten are excluded by ADR-0024), so it moves in steps of 0.125 and the provisional 0.90 already required 8/8 with zero failures tolerated — arithmetically identical to 1.0 while reading as though a miss were acceptable. Set to 1.0; both baselines reproduce byte-for-byte, which is the evidence it is a restatement not a tightening. **`exact_symbol_resolution`'s 0.98 has the same illusion** — 27 cases, 27/27 required — and is left open because it is a Section 19.3 target cited in approved gates | none (post-gate) |

| [0033](0033-exact-symbol-threshold-granularity.md) | The second instance ADR-0032 recorded: `exact_symbol_resolution` scores 27 cases against 0.98, requiring 27/27 with zero failures tolerated. **Kept at 0.98, deliberately not restated as 1.0** — unlike `lexical_resolution`'s internal provisional 0.90, this is a Section 19.3 release target that becomes expressible at ~50 cases, so restating it would tighten a product promise to match an artifact of corpus size. Documented at the constant and pinned by tests; the real fix is corpus size | none (post-gate) |

| [0034](0034-trace-follows-routes.md) | `relation_path_correctness` (0.3182, no gate target) averages **four unrelated causes**, which is why no threshold could mean anything. Fixes one: `trace` never traversed `ROUTES_TO`, so a flow could not cross the HTTP boundary that relation exists to model, and an answer with edges but no buildable path returned an empty `relation_paths` with **no warning**. Now follows routes and warns `RELATION_PATH_UNRESOLVED` on a shortfall; 0.3182 → 0.5000 with no other metric moving | none (post-gate) |

None is superseded. ADR-0008 is the first record to change a published contract
under Section 25, and carries that section's checklist as an explicit table.
ADR-0009 admits the optional vector store the blueprint gates behind its
activation approval, and records why no Section 25 item is triggered by
default.
