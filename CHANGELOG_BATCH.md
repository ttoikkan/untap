# Batch / persistence changelog

## v59

- Introduced `untap_batch.py` as the dedicated batch/persistence layer.
- Extracted the existing validated `run_batch()` implementation from `untap.py`.
- Extracted CSV write/read helpers and the occurrence-aware resume identity/cache implementation without changing the CSV schema or reuse rules.
- Confirmed `status=ok` rows remain the only rows eligible for resume reuse; ambiguous, failed, low-confidence, and rate-limited rows are retried.
- Current parser-generated input identity and original menu text remain authoritative when cached confirmed results are reused.
- HTTP 429 remains fail-fast for the active batch: the current rate-limited result is recorded and unprocessed remaining rows are left for a later `--resume` run.
- Added pure batch/persistence contract tests so these semantics can be checked without a live browser session.

## v60

- No batch ordering, resume/cache, CSV value, or HTTP-429 fail-fast behavior changes.
- Added the explicit `CSV_FIELDS` contract and made `save_csv()` use it as the single definition of persistent column order.
- Added contract coverage proving normalized brewery/beer/ABV/style identity is forwarded unchanged to the matcher.

## v62

- No runtime behavior changes in this module. v62 adds project-level reproducible dependency setup and deterministic CI only.

## v63

- Adds static typing to the normalized-record input and matcher-result output boundaries of `run_batch`, plus CSV/query-file boundary hints.
- Adds a `CsvRow` static contract aligned by tests with the stable `CSV_FIELDS` runtime schema.
- Resume/cache and CSV serialization behavior are unchanged.

## v64

- No batch/CSV/resume behavior changes. v64 adds opt-in search-response timing diagnostics in the Untappd transport/CLI path only.

## v65

- Adds opt-in per-item total elapsed timing and whole-batch elapsed timing behind the existing `--debug-timing` switch.
- Adds aggregate item timing statistics and labels resumed items explicitly.
- Timing does not alter batch iteration, resume selection, matcher calls, rate-limit fail-fast behavior, or CSV persistence.
- Corrected the internal batch timing stats annotation with a local `TypedDict` so mypy can distinguish counters/floats from optional min/max values. Runtime behavior is unchanged.


## v66

- No batch/CSV/resume behavior changes.
- Adds timing-only accounting for wall-clock time outside `search_one` by comparing item total with matcher total.
- Resumed rows retain their existing timing marker and do not fabricate matcher timing.

## v67

- Resets the matcher-owned candidate-parity counters at batch start so each `--debug-timing` run reports only the current batch.
- No CSV, resume, batching, rate-limit, or result behavior changes.
