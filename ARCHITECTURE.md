# Untap architecture contract

Current through v111: strict search replay, shared brewery policy, fallback helpers and package migration. Untap validates TSV input locally, searches through serial browser-context transport, resolves beer identity, and saves lossless JSON plus self-contained HTML. CSV is optional. Continuation, local review, refresh, inspection and local publication have separate orchestration boundaries.

The v110 extractions centralize output serialization and review policy, separate report card data from HTML, and make search discovery phases explicit. They preserve matching, request order, saved schemas and report bytes. Folder creation, journals and recovery-file cleanup remain in the batch and continuation workflows.

## Module ownership and dependency direction

| Module | Responsibility |
| --- | --- |
| `untap.cli` | Installed command dispatcher and shared subcommand composition |
| `untap.run` | Search arguments, local preflight, browser-session orchestration and terminal presentation |
| `untap.parser` | TSV validation, normalization and normalized menu records |
| `untap.batch` | Serial iteration, result callbacks, batch timing and fail-fast handling |
| `untap.brewery_policy` | Pure compatible/conflicting/unknown brewery verdicts and rejection reasons |
| `untap.matcher` | Candidate scoring, discovery orchestration, identity decisions and finalization |
| `untap.transport` | Browser lifecycle, transport, HTTP/page validation, detail extraction and diagnostics |
| `untap.run_output` | CSV schema/export and existing-snapshot JSON/HTML/optional CSV writing |
| `untap.snapshot` | Snapshot construction, validation, persistence and occurrence-aware menu IDs |
| `untap.review_policy` | Selection fingerprints, review row/candidate ordering and candidate eligibility |
| `untap.report_model` | Pure typed report card presentation data |
| `untap.report` | HTML templates, escaping, safe links/assets and page/filter rendering |
| `untap.continue_run` | Saved-run preflight, journal recovery and continuation into fresh folders |
| `untap.refresh` | Selection application/history, reviewed-run creation and optional local publication |
| `untap.local_review` | Local HTTP review session, candidate retrieval actions and saving |
| `untap.manual_candidates` | Explicit candidate retrieval and strict beer-URL validation |
| `untap.refresh_config` / `untap.registry` | Configuration defaults/validation and opt-in registration |
| `untap.identity` | Dependency-free logical archive title identity |
| `untap.publish` | Local archive validation, publication/replacement and index regeneration |
| `untap.inspect` | Explicit raw Algolia inspection without matching decisions |
| `untap.smoke` | Explicit live integration probe |
| `untap.setup` / `untap.version` | Explicit browser installation and the distribution/CLI version |
| `untap.types` | Shared static contracts, with no runtime-layer imports |
| `untap.assets` | Bundled review JavaScript embedded in reports |

The command dispatcher sits above the runtime modules; those modules never import it. Search orchestration calls batch/matcher/transport boundaries. Batch also exposes compatibility CSV names from the output module. Output depends on snapshots, the renderer and shared types, and has no search or publication dependency.

The presentation dependency direction is:

```text
untap.run_output -> untap.report -> untap.report_model -> untap.review_policy
       |                 |                |                      |
       v                 +----------------+----------------> untap.types
untap.snapshot <--------------------------+
       |
       v
untap.types

untap.refresh / untap.local_review -> untap.review_policy
untap.refresh --------------------> untap.run_output / untap.report
```

The lines show principal dependencies, rather than every import. Review policy depends only on shared types. The renderer, model, snapshots, output and publisher cannot transitively depend on batch, matcher, transport or Playwright. Refresh uses the output module directly for serialization; it no longer imports batch for CSV. Local review calls refresh's existing selection/output workflow. Refresh may explicitly publish, but search, registry and rendering do not transitively import the publisher.

Dependency tests discover runtime modules and enforce these boundaries. An import reference does not authorize filesystem or network work: pure policy and presentation preparation perform neither.

## Input and command composition

The parser accepts four-column TSV: brewery, beer, ABV and style. Style may be empty, but the fourth column must remain. Legacy layouts are rejected before browser startup. The normalized runtime field set remains `NORMALIZED_RECORD_FIELDS`:

```text
brewery, beer, style, menu_abv, query, original
```

`NormalizedMenuRecord` describes the same fields. Raw-menu recognition, fail-closed validation and normalization belong in the parser; browser, HTTP and output lifecycle behavior do not.

`untap.cli` composes `run`, `review`, `refresh`, `publish`, `inspect` and `smoke` from each tool's argument definitions and execution function. Legacy option-led and query forms delegate to `untap.run.main`; separate installed commands and source scripts remain supported. A leading exact subcommand name is reserved; `run` or `--` explicitly disambiguates such queries.

Help, version reporting, menu validation and offline report operations remain browser-free. Playwright is imported lazily inside `untappd_browser_page`. CLI boundaries translate browser-availability errors into clean exits with installation guidance. Matching and transport errors retain their established behavior.

## Search discovery phases

`search_one(page, query, min_score, debug, expected_beer, expected_brewery, expected_abv, expected_style)` remains the external matching entry point. `_search_one_impl` resets per-beer diagnostics and sequences:

1. `_retrieve_primary_discovery`: page-zero transport, matched response/page selection, candidate construction and primary diagnostics. It returns `_PrimaryDiscovery` or a terminal transport/HTTP 429 result.
2. `_expand_primary_discovery`: existing evaluation and conditional paging strategies. It passes the captured request, hit count and validated page to `evaluate_and_expand_candidates`, retaining ordinary and ABV-sorted diagnostics. It returns `_SearchDiscovery` or a terminal HTTP 429 result.
3. `_recover_search_discovery`: ordered fallback queries, identity filters and selection of the discovery set used downstream. It returns updated discovery or a terminal HTTP 429 result.
4. `_resolve_discovered_candidates`: pure identity decision followed by impure finalization.

These helpers stay within the matcher. `_PrimaryDiscovery` and `_SearchDiscovery` are internal phase state, not saved schemas. Requests are serial; extracting a phase adds no retry, parallelism or transport path. Captured page metadata must remain paired with the query and candidates that produced it.

Conditional expansion uses the existing ambiguity, weak-match, release-qualifier and same-ABV-family triggers, with ordinary or eligible ABV-sorted strategies. `evaluate_and_expand_candidates` is shared by primary and fallback attempts; it retains paging limits, response validation and early stopping.

Recovery runs only for missing, low-score or ABV-conflicting top candidates. Generic trailing-token relaxation is enabled only after a true zero-hit primary search. Leading-name, trailing-identity and brewery filters retain their original scope. `_run_filtered_fallback` runs one retrieval and applies named recovered-identity, trailing-identity and beer-only brewery filters in order. `_adopt_fallback` moves candidates, metadata page and diagnostics together. Recovery stops at the first plausible or meaningfully ambiguous set; otherwise it retains the strongest weak set while trying broader queries. A winning fallback replaces its candidate and initial-page metadata together. HTTP 429 terminates before another request or finalization.

The brewery predicate and rejection reason have one owner: `untap.brewery_policy`. Its immutable verdict is compatible, conflicting or unknown. Recovery keeps its adoption gate, while the decision stage uses the same verdict for eligibility. Unknown evidence stays eligible. Rejected beer-only candidates become inspection evidence when no candidates survive; they cannot displace useful weak primary evidence.

## Pure identity decision and finalization

`decide_candidates(candidates, expected, min_score, discovery, collect_diagnostics=False)` consumes ranked candidates and plain expected/discovery records. It returns an internal `Decision` with kind, rule, provisional candidate, alternatives, same-ABV variants, reason, warning, diagnostics and excluded conflict evidence.

It copies candidate input and does not mutate inputs, print, import Playwright, perform I/O, update counters or read timing state. Diagnostic messages are returned as data. Rule names remain internal and are not serialized in results.

Production precedence is:

1. Fail on empty retrieval, retaining any incomplete-search warning.
2. Exclude known ABV conflicts; fail if none survive.
3. Exclude explicit brewery conflicts under the overlap/collaboration policy; fail if none survive. Unknown brewery evidence is retained.
4. Recompute ambiguity after exclusions. An explicitly retired exact release competing with a current same-ABV vintage requires review, including after incomplete discovery or review-only fallback.
5. With complete discovery and no review-only fallback, try exact-base, exact-numbered, then unique-exact-identity. Accepted exact rules clear prior ambiguity and move the candidate first without changing scores.
6. Review-only fallback supplies a review reason. Incomplete/early-stopped discovery enforces review and its warning; no score or exact rule can select.
7. Two or more same-ABV family variants produce family ambiguity before other ambiguity explanations.
8. Any remaining ambiguity requires review.
9. Without exact acceptance, a top score below the requested minimum is low confidence.
10. Otherwise provisionally select the top candidate.

Rank and stable tie order remain discovery input order. Exact-numbered and unique-exact rules may differ for equal-score sibling order while selecting the same explicit identity. Tests characterize that behavior rather than introducing a tie-breaker.

`EXACT_BASE_FLAVOR_QUALIFIERS` and `EXACT_BASE_PROCESS_QUALIFIER_RE` define the bounded exact-base extensions established by regression menus. They do not remove flavors generally or affect scoring. Unknown qualifiers block that rule. Extending the allowlist requires matching fixtures and explicit policy review. The production/vintage guard requires explicit opposing production states and a compatible same-brewery/name-family vintage at exact ABV; rating counts are not identity evidence.

`_resolve_discovered_candidates` builds the decision records, prints diagnostics in their established order, then calls `_finalize_decision`. Finalization recovers captured brewery/style metadata, constructs confirmation from complete Algolia metadata or validates a detail page, records counters/timing and builds `MatchResult`. A selected decision may finalize as `ok`, `failed` or `rate_limited`.

When all candidates conflict on ABV or brewery, finalization retains up to ten ordered `excluded_candidates` with individual exclusion reasons. They are inspection evidence, separate from selectable alternatives. Beer-only recovery keeps its existing brewery eligibility filter to preserve fallback adoption, but carries rejected candidates as internal discovery evidence. If no candidates survive, the decision reports the brewery conflict and exposes those inspection links; rejected fallback candidates never replace a useful earlier result. This additive output behavior was introduced in v109; v110 preserves it.

## Transport, diagnostics and rate limits

The transport owns browser lifecycle, event-driven waits, network capture, browser-context Algolia requests, response/query/index/page pairing, detail-page validation and HTTP observations. It does not decide beer identity.

Search uses the serial self-healing page-zero transport. A non-429 direct transport failure invalidates the cached request shape and permits one UI-driven recapture for that query. HTTP 429 never triggers recapture or retries. Browser POST and response-body reading have bounded deadlines.

Identity selection and metadata completeness are separate contracts. A strong identity match can still lack a usable URL, ABV or ratings. Finalization validates confirmation metadata independently: a selected candidate without a usable URL becomes low confidence without detail navigation; incomplete metadata with a usable URL may trigger validated detail retrieval. Seeded finalization invariants cover absent keys and null values, and directed cases cover ambiguous alternative lists. Pure decision tests alone cannot establish safe browser behavior.

Algolia metadata is authoritative for complete confirmed results. Detail fallback validates HTTP status, selected beer URL and page heading before confirmation. Detail HTTP 429 propagates to batch fail-fast handling. This supersedes the historical DOM-authority and diagnostic-only direct-transport descriptions from earlier releases.

`--shadow-search-transport N` explicitly enables bounded diagnostic replays for successful UI captures. Replay candidates do not affect matching; replay HTTP 429 stops further traffic. Alias analysis and detail/Algolia parity diagnostics likewise do not change identity policy. Live transport requests belong in the transport layer, not in parser or presentation modules.

Timing is opt-in observation. Transport owns browser/request timings, matcher owns named matching phases, and batch owns item/batch totals. The CLI configures instrumentation and prints summaries. Nested transport timings must not be double-counted with matcher phases. Timing cannot justify bypassing evidence, weakening ambiguity, issuing parallel requests or changing rate-limit behavior.

## Saved runs, output and continuation

Batch consumes normalized menu records or query strings and emits results through checkpoint callbacks. It owns serial iteration and stops after a rate-limited result, emitting identity-preserving placeholders for remaining rows. CLI batch orchestration owns the run directory, input manifest, flushed journal, shutdown save and cleanup.

`untap.snapshot` owns snapshot construction/validation and occurrence-aware IDs derived from input identity. JSON is lossless persistence; schema versioning is independent of the CLI version. Snapshot saves refuse overwriting an existing snapshot.

`untap.run_output` owns `CSV_FIELDS`, CSV serialization and writing an existing snapshot's JSON, HTML and optional CSV into a caller-reserved folder. It does not create folders, change metadata or manage recovery files. CSV export prefixes formula-leading text cells with an apostrophe; numeric cells and saved JSON/HTML are unchanged. `untap.batch.save_csv`/`CSV_FIELDS` and the source CLI's CSV export remain compatibility names.

Save order and dates are preserved: batch writes JSON, optional CSV, then HTML using the renderer's current date; continuation writes JSON, HTML using saved snapshot metadata, then optional CSV. Refresh renders before creating its output directory and passes the prepared HTML to the shared writer. Output failures propagate to workflow callers.

Normal batches reserve unique timestamp/title directories under cwd-relative `results/`. `--debug` shares terminal output with a saved `debug.txt` transcript. During execution, `results.input.json` records the complete menu and each completed result is flushed to `results.partial.jsonl`. Shutdown saves unfinished rows as not attempted. Recovery files are removed only after complete final output succeeds. Journal/checkpoint implementation remains separate in batch and continuation; CSV resume machinery is removed.

`untap.continue_run` validates saved runs and recovers interrupted journals. It searches only rate-limited or not-attempted rows in a fresh sibling folder, preserving completed failed/ambiguous results, item IDs, decisions and candidate additions. Torn final journal records are tolerated with warnings; damaged complete records and identity mismatches fail closed. Legacy journal recovery requires the original menu when the manifest is unavailable.

Incomplete runs cannot be published or registered. No workflow silently overwrites its source run.

## Review policy, presentation and local review

`untap.review_policy` owns the full-content selection fingerprint, row rating order, candidate precedence/order/limits and selectable-candidate lookup. It depends only on shared types and performs no rendering, persistence, retrieval or mutation. Selection fingerprints are distinct from logical archive title identity: an export must match the exact report data, title and date.

Same-ABV variants take precedence over general alternatives. Candidate order follows score and name; the ordinary candidate list is limited to ten while explicit user additions remain available. Excluded inspection links are never selectable. Refresh and local review import policy directly; renderer helper names remain compatibility exports.

`untap.report_model` prepares frozen typed row/card data: occurrence-aware IDs, labels, metadata, production state, candidates, user-added verification notes, best guesses and excluded links. It depends on types, policy and snapshot IDs, and contains no HTML or I/O. The model is never saved into snapshots.

`untap.report` owns templates, escaping, safe beer/asset URLs, page metadata and filter markup. Top-level rows use shared rating order; review candidates remain grouped by input. Style groups derive from canonical `type_name` values rather than a fixed vocabulary. JSON preserves data; HTML presents and supports review; CSV is an optional export. Review explanations use saved reasons and candidate/menu ABV values without applying new matching rules. A repeated search warning is shown once.

Reports embed their scripts and require no external script/style files. They issue no automatic search requests; displayed label images may load from Untappd assets. Static review stores browser choices and exports them for explicit application. Local-review mode can explicitly retrieve candidates through its localhost endpoint.

`untap.refresh` validates selection payloads before network/filesystem mutation, applies selections with decision history, clears stale selected-beer data, and writes new reviewed runs. `untap.manual_candidates` owns strict beer-URL parsing and explicit retrieval; adding a URL is not confirmation. Pending URLs require an explicit fetch action or `--fetch-candidates`.

Freshness is explicit: snapshot `created_at` remains the source-data save time, report `date` remains the menu date, and `report.rebuilt_at` records a successful new presentation. Offline refresh never claims ratings were fetched. Reviewed output preparation deep-copies the snapshot before stamping rebuild metadata. Optional source/rebuild HTML metadata propagates to archive cards; legacy reports need neither field. The CLI writes a source-side `refresh-status.json` and archive `.untap-refresh-status.json` after each attempt. Failed refresh/publication updates the archive index while leaving published report bytes unchanged. Status persistence failures are diagnostic and do not hide the operation's original outcome; corrupt optional archive status is ignored with a warning rather than blocking unrelated publication.


`untap.local_review` owns the localhost HTTP session, per-session token and fetch/save actions. Candidate additions remain pending until saved into a new run. Reopening a manual selection restores original alternatives while retaining added candidates. Renderer injection checks its marker, and unexpected server errors return JSON rather than dropping the connection.

## Registry, refresh configuration and publication

`untap.refresh_config` provides configuration validation/defaults. `untap.registry` registers completed snapshots by logical title, skips missing sources with warnings, and leaves existing registrations unchanged. Configuration paths are relative to the configuration file. Batch refresh processes independently validated entries and reports failures without rolling back successful entries.

`untap.identity` owns dependency-free logical title normalization shared by registry and publisher. `untap.publish` consumes validated HTML metadata and operates only on the local archive. It validates existing reports, derives dated filenames, copies completed reports and rebuilds the newest-first index. It owns no Git, credentials, remote deployment, browser or network work.

Publication refuses an existing logical title unless `--replace` is explicit. Replacement requires exactly one match and preserves the archive filename/public URL. Malformed metadata, duplicate logical identities and unrelated filename collisions fail closed. If index update fails, the prior report is restored. Git commit and push remain external actions.

## Installation, tests and maintenance rules

Runtime modules live inside the `untap/` package, whose packages and compatibility scripts are explicitly declared in `pyproject.toml`. Review JavaScript lives in `untap.assets` and is read with `importlib.resources`. `python3 -m untap` uses the unified dispatcher. The seven historical source scripts remain thin entry-point wrappers; six uniquely named wrappers are also installed for legacy module invocations. The old internal flat module import paths are replaced by package imports. `untap.version` is the single distribution/CLI version source. `untap-install-browser` explicitly invokes Playwright using the installed interpreter; searches never download Chromium implicitly.

Python 3.9 is the declared minimum. Runtime Playwright and development mypy versions are pinned in `requirements.txt`/`requirements-dev.txt`. Type checking covers the runtime modules and asset package, while runtime validators remain authoritative:

```bash
python3 -m mypy untap untap_*.py
```

Tests are a package under `tests/`; fixtures live in `tests/testdata/`. Cross-test imports use package-qualified names and runtime-file checks resolve the repository root. Default discovery remains supported; the explicit command is:

```bash
python3 -B -m unittest discover -s tests -t .
```

The suite retains these contracts:

- `decision_v107.json` freezes 24 decision/output cases. `decision_review_links.json` overlays the intentional v109 conflict-link and continuation-guidance changes; `decision_explanations_html.json` separately pins the intended review-explanation presentation changes, leaving matching/JSON/CSV expectations intact.
- The seeded invariant harness checks determinism, immutability, identity compatibility, precedence, incomplete-discovery safety, minimum-score boundaries and same-ABV family review. Defaults are 2,000 cases with seed 107; failures include reproducible reduced cases.
- `report_model_v109.json` preserves 40 pre-extraction fixed-date HTML cases; `report_explanations_html.json` pins their intended updated presentation hashes, including manual choices, production state, user additions, escaping and ordering.
- `search_recovery_v109.json` pins nine pre-extraction search request/outcome sequences; direct tests cover HTTP 429 termination and phase metadata propagation.
- Strict corpus tests fake only Playwright I/O: UI request/response events and browser-context fetches. Request construction, response decoding, candidate construction, expansion and decisions run normally. Every query, page, index and parameter is replayed in order; unexpected and unused requests fail. The initial sanitized payload-shaped fixtures are hand-authored, not claimed as live recordings. Offline `tests.corpus_tools` can record one explicit live flow into a draft and promote it only after shared status/shape validation, sanitization checks and complete strict replay. Every malformed response retains its status; refusal blocks further fetch/navigation, and failure cleanup removes the recording listener and transport authority. Expected statuses/fields are explicit. Replay preserves complete UI request batches, overriding search queries with typed input. They cover conflicting fallback evidence, primary retention, metadata, conditional expansion, missing page metadata and HTTP 429.
- The explicit smoke test compares already fetched responses against the corpus required field/type shape. Additions are tolerated; missing or changed fields produce a diagnostic warning without more requests or changes to matching or exit status.
- Packaging tests check package discovery and compatibility scripts without building a wheel. Optional installed-wheel tests exercise commands outside the checkout, bundled assets, missing-browser errors and output equivalence.
- Legacy menu fixtures verify unsupported formats are rejected before browser startup.

Increase invariant coverage explicitly:

```bash
UNTAP_INVARIANT_SEED=108 UNTAP_INVARIANT_CASES=10000 python3 -B -m unittest tests.test_untap_decision_invariants
```

Set `UNTAP_TEST_ENV` to a fresh wheel installation to enable installed checks. `untap smoke` is an explicit live integration probe, separate from deterministic tests; it checks transport and identity contracts without pinning mutable rating values or probing rate-limit thresholds.

Validation remains manual/local; no scheduled or GitHub automation is part of the project. Live checks compare statuses and selected beer IDs/URLs, not mutable ratings. Structural changes must have a concrete benefit, preserve established behavior unless intentionally changing it, and add boundary/failure coverage appropriate to their risk. Historical implementation chronology belongs in `CHANGELOG.md` rather than competing descriptions of the current architecture.
