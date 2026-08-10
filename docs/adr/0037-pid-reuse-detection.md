# ADR-0037: An owner stamp records a process instance, not a pid

- Status: accepted
- Date: 2026-08-10
- Decision owners: user/product and implementing agent
- Supersedes: none

## Context

`indexing/ownership.py` decides whether an interrupted index run may be healed.
Healing a run whose owner is alive is not recovery, it is corruption, so the
check is deliberately conservative: an owner that still exists is left alone.

A pid is not an owner. It is a **slot the operating system reassigns.** If a
dead owner's pid is reissued before CodeAtlas next starts, `process_is_alive`
answers `True` for a process that has nothing to do with the run, recovery
leaves the job alone, and that repository stays blocked from reindexing —
permanently, because nothing about the situation changes on its own.

The limitation was declared at the **Phase 6 gate on 2026-07-29** and carried
through the Phase 7 gate as accepted open work. `codeatlas doctor` names the
blocking run and its pid, so the failure is visible rather than silent, but a
user's only remedy is to read that output and know what it means.

The module's own docstring recorded why it stayed open:

> Closing it needs the owner's process start time, which has no portable source
> without a new dependency.

**That reasoning was half right, and the wrong half kept the item open for
twelve days.** There is no *portable* source. But `AGENTS.md` Section 5 names a
local Windows 11 workstation as the primary supported environment, and on
Windows the source is `GetProcessTimes` — in `kernel32`, beside the
`OpenProcess` call this very module already makes through `ctypes`. Linux has
`/proc/<pid>/stat` field 22. Only macOS genuinely lacks one, and it is not a
supported environment.

The blocker was never the dependency. It was scoping the requirement to
"portable" when the product is not.

## Decision

**An owner stamp records the owner's process start time alongside its pid, and
liveness compares both.** A pid whose live process started at a different
moment is a reused slot whose real owner is gone — recoverable, not protected.

Scope and limits, all deliberate:

- `process_start_time(pid) -> int | None` returns an **opaque comparable
  integer**, not a wall-clock time. Windows returns the creation `FILETIME` as
  one integer; Linux returns clock ticks since boot. The two are never compared
  across platforms, because `owner_is_live` only ever compares a stamp against
  a reading taken on the same machine.
- **`None` means unknown and must read as alive.** An unopenable handle, an
  unsupported platform, or an unparseable `/proc` entry all leave the run
  alone. Guessing "dead" costs data; guessing "alive" costs a delayed cleanup.
- **A stamp without `started_at` keeps the behaviour it was written under.**
  Databases written by every build through 2026-08-10 have pid-only stamps and
  no start time can be inferred for them. They stay pid-only rather than being
  reinterpreted.
- `current_owner()` **omits** the key rather than storing `None` when the
  platform cannot answer, so the stamp is byte-shaped exactly as before on
  those platforms.

## Alternatives

**Add `psutil`.** It answers portably, including on macOS. Rejected: it is a new
runtime dependency for one comparison that two already-available system
facilities answer on both supported platforms, and `AGENTS.md` Section 6 says
not to add a dependency for something the standard library covers. It would
also grow the packaged tree, which is already a carried 1.05 GB open item.

**Detect reuse by re-checking the process's image name.** A reassigned pid
usually belongs to an unrelated executable. Rejected: it is a heuristic wearing
a fact's clothes — a *second CodeAtlas process* could legitimately receive the
old pid, and then the image name matches while the owner is still wrong. Start
time distinguishes instances; the executable name distinguishes programs, which
is a different question.

**Expire a stamp after a timeout.** Simple, and needs no system call. Rejected
for the reason the module exists: an index of a large repository can legitimately
run longer than any timeout short enough to be useful, so this would heal live
runs — precisely the corruption being prevented.

**Leave it, since `doctor` reports it.** This was the standing position.
Rejected now that the cost is one function: a diagnostic that requires the user
to interpret it is not a substitute for the system being correct.

## Consequences

Positive: a reassigned pid no longer blocks a repository from reindexing, on
both supported platforms. The failure it closes was permanent and needed manual
diagnosis. Recovery gets *strictly* more precise — no case that was previously
healed is now protected, and no case that was previously protected is now healed
except the reused-pid case this record is about.

Negative and accepted:

- **macOS keeps the old behaviour.** Not a supported environment; stated rather
  than hidden.
- **One extra system call** per non-self-owned stamp during recovery. Recovery
  runs in `build_services`, and the call is only reached after
  `process_is_alive` already returned `True`, so it is bounded by the number of
  open jobs — in practice zero or one.
- **The Windows and Linux values are not interchangeable.** A database moved
  between platforms carries stamps the other cannot compare. This is harmless:
  the pid check runs first, and a mismatch falls back to leaving the run alone.
  Recorded because it is the non-obvious property of an opaque comparable.

No contract, schema, or migration change. `contract_version` stays `1.1`,
`SCHEMA_VERSION` stays `14`. The owner stamp lives in the `index_jobs.diagnostics`
JSON blob, which is unversioned free-form diagnostics by design, and the new key
is additive and optional.

## Security and Privacy

None. A process start time is local machine state, never leaves the process, is
not logged, and is not rendered to any client — `codeatlas doctor` continues to
report the pid only. No new data crosses a trust boundary, and nothing here
touches repository content, prompts, or provider traffic.

## Migration and Rollback

No migration. Forward: new runs carry `started_at`; existing rows do not and are
read exactly as before. Rollback is deleting the comparison — an older build
reading a newer stamp ignores the unknown key, because it reads `pid` and
`token` by name.

Verified by mutation rather than by assertion, both failures observed:

- forcing the comparison to `True` fails
  `test_a_reused_pid_does_not_keep_a_dead_owner_alive` **and**
  `test_recovery_strands_a_run_whose_owner_s_pid_was_reused`;
- forcing it to `False` fails
  `test_a_matching_start_time_still_reports_the_owner_alive`, which is the guard
  against "return dead whenever a start time is present" — an implementation
  that satisfies the first test and corrupts live indexes.

The four pre-existing ownership tests are the regression guard for the
token fast-path and all still pass.

## Approval

Recorded by the implementing agent on 2026-08-10 as part of the project
closeout, under the user's instruction to close the remaining substantial
items. No Section 25 scope item is triggered: no new dependency, no contract
change, no schema change, no network exposure, no change to what leaves the
machine.
