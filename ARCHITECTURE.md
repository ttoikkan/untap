# Untap architecture contract

Current through v108. The CLI validates TSV locally, then orchestrates batch matching and browser transport. HTML/JSON are the default outputs; CSV is optional. Snapshot refresh, local review, candidate retrieval and refresh registration are separate boundaries. V103 adds interruption journals, incomplete-run guards and a shared report-identity module.

V107 review corrections enforce brewery consistency and incomplete-discovery review at final resolution. The transport owns HTTP/page validation and bounded browser requests, and raises ordinary browser-availability errors; CLI boundaries translate those errors into clean command exits. Algolia request/result pairing is shared by transport, expansion and inspection. Shadow replay remains diagnostic except that HTTP 429 must stop further traffic.

## Pure candidate decision stage (v108, v107 baseline)

`untap_matcher.decide_candidates(candidates, expected, min_score, discovery, collect_diagnostics=False)` consumes already-ranked candidates and plain expected/discovery records. It returns the internal `Decision` TypedDict, including `kind`, `rule`, a provisional candidate, alternatives, same-ABV variants, reason, warning and diagnostic messages. It copies candidates and does not mutate inputs, print, import Playwright, perform network work, update counters or read timing state. Debug messages are data, not callbacks.

`_resolve_discovered_candidates` remains the compatibility boundary. It creates the records, prints returned diagnostics in their existing order, then calls `_finalize_decision`. Finalization recovers captured brewery/style metadata, uses Algolia confirmation or validates a detail page, records counters/timing, and builds the unchanged `MatchResult`. A `selected` decision may finalize as `ok`, `failed` or `rate_limited`; it is not a confirmation. `Decision.rule` is internal and is not written to JSON, CSV or HTML.

The production precedence is:

1. No candidates: fail, retaining any incomplete-search warning.
2. Exclude known ABV conflicts; fail if none survive.
3. Exclude explicit brewery conflicts using the existing overlap/collaboration policy; fail if none survive. Unknown brewery evidence is preserved.
4. Recompute ambiguity after exclusions. A retired exact release competing with a current same-ABV vintage requires review even when discovery is incomplete or fallback is review-only.
5. With complete discovery and no review-only fallback, try exact-base, exact-numbered, then unique-exact-identity. An accepted exact rule clears prior ambiguity and moves its candidate to the front without changing scores.
6. Review-only fallback sets a review reason. Incomplete/early-stopped discovery then enforces review and its warning; no score or exact rule can produce a selection.
7. Two or more same-ABV family variants produce the family ambiguity explanation, ahead of the remaining ambiguity explanation.
8. Any remaining ambiguity reason requires review.
9. Without an exact acceptance, a top score below the requested minimum is low confidence.
10. Otherwise select the top candidate provisionally for finalization.

Rank and tie order remain the v107 input order. There is no new tie-breaker. For example, an equal-score numbered pair can use `exact_numbered` or `unique_exact_identity` depending on which sibling comes first, while choosing the same explicit identity. This is characterized rather than normalized during extraction.

### Characterization and invariant contracts

`testdata/decision_v107.json` freezes 24 v107 cases, including Banishing 3, Tripla identities, Boston Lager, Imprint, Humble Sea ABV conflict, production/vintage conflicts, incomplete discovery, review-only fallback, captured metadata recovery and detail failures/rate limits. The characterization test checks full results, debug text and counter deltas, plus byte hashes of fixed-date HTML, CSV and snapshots.

The seeded invariant harness uses real scoring and stable ranking, directed generation for rare rule interactions, and coherent initial ambiguity over eligible candidates. It checks determinism and input immutability; ABV/brewery compatibility of selections; no selection after incomplete discovery; loss of uniqueness after adding a distinct exact identity or removing required evidence; production evidence and precedence; excluded distractors with surviving candidates; valid possible finalization statuses; inclusive minimum-score acceptance when no earlier rule overrides it; and same-ABV family review after higher-priority identity guards. Equal-score behavior is pinned by a directed characterization instead of an unsupported permutation invariant. Empty retrieval and all-rejected retrieval intentionally retain distinct failure explanations.

The default is 2,000 cases with seed 107, taking about 2–3 seconds locally. Failures include seed, case index and a reduced candidate list preserving the failing invariant and generator preconditions. Increase coverage explicitly:

```bash
UNTAP_INVARIANT_SEED=108 UNTAP_INVARIANT_CASES=10000 python3 -m unittest test_untap_decision_invariants
```

Discovery, fallback and live response compatibility remain outside the pure-stage tests. Maintainer reports the live test works. Future live comparisons should check statuses and selected URLs against saved baseline runs.

## Dependency flow

```text
raw menu text
    |
    v
untap_parser.py
    |  validated NormalizedMenuRecord
    v
untap_batch.py ------> untap_matcher.py ------> untap_untappd.py
    ^                         ^                         |
    |                         |                         |
    +-------------------------+-------------------------+
                              |
                           untap.py
                    CLI / orchestration / display

untap_smoke.py -----> untap_matcher.py / untap_untappd.py / untap_types.py
     manual live health check only; no parser or batch dependency

untap.py ------------> untap_report.py ------> untap_types.py
     completed results   static HTML only; no batch/parser/matcher/transport dependency

untap_types.py  ---> shared static contracts only
                   (no product decisions / no upward imports)
```

`untap_types.py` is a contract module, not a new behavioral layer. It contains typing declarations only and may be imported by parser/matcher/batch modules without changing ownership or runtime data flow.

## Parser contract

The parser owns raw-menu format recognition, fail-closed structural validation, normalization, and normalized-record validation. Its runtime field set remains `NORMALIZED_RECORD_FIELDS`:

```text
brewery, beer, style, menu_abv, query, original
```

v63 adds the matching static `NormalizedMenuRecord` TypedDict. Tests require the runtime and static field sets to remain identical.

No browser, Playwright, Algolia, HTTP, CSV, or resume behavior belongs in the parser.

## Matcher contract

`search_one(page, query, min_score, debug, expected_beer, expected_brewery, expected_abv, expected_style)` remains the primary entry point. The matcher owns identity scoring, ambiguity decisions, ABV-family logic, fallbacks, and candidate selection.

Its runtime status vocabulary remains `MATCH_RESULT_STATUSES`; v63 adds a `MatchStatus` Literal and `MatchResult`/candidate TypedDicts whose contract is checked against it.

The matcher may use Untappd transport primitives but should not own browser lifecycle, CLI behavior, CSV persistence, or raw-menu parsing.

## Untappd transport contract

The transport owns browser lifecycle, event-driven search waits, network capture, Algolia request/response handling/replay, DOM discovery, detail extraction, diagnostics, and HTTP observations. It does not decide which beer identity is correct.

In v73 the cached direct-search request shape is explicitly recoverable state, not a permanent run invariant. A non-429 direct transport failure invalidates it and permits exactly one UI-driven recapture for the affected query. A 429 never triggers that path. `AlgoliaRequestRecord`, `AlgoliaTransportEvent`, and `SearchTransportResult` provide static contracts for this boundary.

Playwright remains lazily imported by `untappd_browser_page()`, preserving the preflight invariant that invalid or validation-only menu workflows perform no browser startup.

## Batch/persistence contract

The batch layer consumes validated `NormalizedMenuRecord` values or plain query strings and returns `MatchResult` values. It owns iteration, optional CSV serialization, per-result checkpoint callbacks and fail-fast handling once a matcher result reports HTTP 429. Unattempted rows retain input identity; the CLI journals each completed result and saves snapshots in a finally block.

The stable CSV order remains `CSV_FIELDS`; v63 adds a corresponding `CsvRow` TypedDict and contract test. CSV resume has been removed.

## HTML report contract (v77–v80)

`untap_report.py` owns static human-facing HTML rendering from already completed `MatchResult` records. It may depend on shared types and lightweight snapshot item-ID helpers; it must not import parser, matcher, batch, transport, smoke, or Playwright layers. The CLI may invoke it after a batch completes.

The report is self-contained and responsive, makes no network requests, and does not alter result data. Confirmed beers are ordered by Untappd rating descending. Ambiguous candidates remain grouped by input result and are ordered by match score descending. Canonical Untappd `/b/` URLs are rendered as links for confirmed beers and review candidates when available. JSON is the lossless persistence format; HTML provides review and presentation; CSV is an optional export.

v78 adds an optional descriptive title supplied by the CLI through `--report-title`. The renderer also embeds simple machine-readable metadata for report title, generation date, total beers, confirmed beers, and needs-review count. That metadata is presentation/archive context only; no GitHub or publishing responsibility is introduced into Untap.

v80 adds a small inline client-side style filter while keeping the report one self-contained static HTML file. Filter groups are not predefined: they are derived from canonical Untappd `type_name` values present in the completed results, using the leading component before the structural `" - "` subtype separator. Only present groups are rendered, alphabetically, and all begin enabled. Detailed `type_name` values remain visible. Ambiguity candidate projections now preserve `type_name` so Needs review candidates participate in the same presentation contract; this is metadata propagation only and does not alter candidate scoring or ambiguity decisions.

## Local archive publisher contract (v79–v81)

`untap_publish.py` is a standalone local-filesystem utility, not part of the Untap runtime data flow. It imports only the dependency-free `untap_identity` helper among Untap modules and is not imported by `untap.py` or `untap_report.py`. Its input contract is only the machine-readable `untap-*` metadata embedded in completed v78+ HTML reports.

The publisher owns archive validation, safe dated filename derivation for first publication, copying a completed report into a local `reports/` directory, logical report identity (shared with registration through `untap_identity.py`), and deterministic newest-first regeneration of the static archive `index.html`. The normalized descriptive report title is the logical archive identity; the embedded report date is generation metadata rather than identity. It must fail closed on malformed metadata and must never silently replace an existing logical report. Existing archived HTML reports are validated before archive mutation.

v81 adds one explicit exception to the replacement guard: the caller may request `--replace` for exactly one existing logical title match. Matching is independent of regeneration date, and the existing archive filename is preserved so the public URL remains stable. Replacement remains opt-in, runs the same source/archive validation before mutation, removes the old entry from the regenerated index before adding the replacement metadata, and restores the previous report if the index update fails. Multiple existing logical-title matches fail closed, and a date/slug filename collision belonging to another title is never replaceable. Supplying `--replace` when no logical title match exists is equivalent to a normal new publication.

The publisher deliberately does **not** own Git, GitHub credentials, GitHub APIs, GitHub Pages deployment, browser automation, or any network operation. It may print suggested Git commands after local publication, but committing and pushing remain explicit external actions. This preserves the boundary `Untap report generation -> completed HTML artifact -> local publisher -> user-controlled Git publication`.

## CLI contract

`untap.py` owns argument parsing, menu preflight orchestration, browser-session orchestration, and user-facing presentation. It should not accumulate parser heuristics, matching rules, direct Algolia mechanics, or CSV/resume implementation.

## Static typing rule (v63)

Typing is deliberately incremental and boundary-first. Runtime validators remain authoritative safety checks. New functional work should preserve or improve type coverage at touched module boundaries, but v63 does not require wholesale annotation of internal helpers solely for annotation coverage.

The static checker is pinned in `requirements-dev.txt` and is run manually/local with:

```text
python -m mypy untap*.py
```

## Reproducible local environment

`requirements.txt` pins Playwright 1.57.0. `requirements-dev.txt` pins mypy 1.14.1. Chromium is installed through Playwright. Untap currently uses a manual/local-only validation model: static checking, deterministic tests, smoke checks, and live regressions are run locally as needed.

There is no GitHub automation in the project. External drift and rate limits are covered by the manual live smoke test and deliberate local live regression.

## Refactoring rule after v60

Future structural changes should be driven by functionality, deployment, or real defects. New behavioral modules should be introduced only when a concrete responsibility cannot be maintained cleanly inside the current boundaries. Architecture-only decomposition is not a roadmap goal.

## v64 performance instrumentation boundary

Performance measurement remains an observation concern, not a matcher-policy concern. The optional `--debug-timing` switch is parsed by the CLI and configures transport-local instrumentation in `untap_untappd.py`. The matcher and batch layers do not receive timing parameters and do not change their decisions when timing is enabled. v64 measures only search submission to exact Algolia response; future optimization proposals should use this evidence without weakening identity or ambiguity safeguards.



## v65 timing diagnostics

`--debug-timing` remains observability-only. Transport-owned measurements cover search-response waits and detail-page navigation/extraction. Batch-owned measurements cover per-item and whole-batch elapsed time. The CLI only enables diagnostics and prints summaries. Timing must not become a reason to bypass matcher evidence, add parallelism, increase requests, or weaken ambiguity protection.

## v66 timing accounting

v66 extends observability into the matcher without changing matcher policy. The matcher still receives no timing parameter; it only consults the existing transport-owned opt-in timing flag. Named matcher phase timers surround already-existing calls and are non-overlapping at the matcher level. The transport's more detailed search-response and detail navigation/extraction measurements are nested views and must not be double-counted when reconciling total time.

The accounting hierarchy is:

`item total = matcher total + batch overhead outside matcher`

and approximately:

`matcher total = named matcher phases + matcher residual / unaccounted`

This hierarchy exists solely to locate performance cost. It must not be used to bypass identity evidence, weaken ambiguity safeguards, add parallel requests, or change HTTP-429 behavior.


## v67 candidate-discovery parity boundary

v67 adds a shadow observation inside `untap_matcher.py` after the exact page-0 Algolia response has already been captured. The matcher converts those captured hits into candidate-shaped dictionaries and compares them with the existing DOM-derived candidates only when `--debug-timing` is enabled. The shadow path issues no requests and does not cross into transport ownership. DOM candidates remain the sole authoritative input to matching decisions. This preserves the post-v60 rule that performance work must not weaken identity or ambiguity safeguards. A future switch away from DOM discovery requires demonstrated parity rather than assumption.

## v69 measurement boundary

v69 adds shadow-only comparison after a confirmed detail page has been extracted. The selected Algolia candidate and the detail-page result are compared for independently available beer name, rating, ratings count, and ABV. Detail-page output remains authoritative. Brewery and `type_name` are not treated as independent parity fields because current detail extraction obtains them from search metadata. The comparison issues no requests and cannot influence matching decisions.


## v70 confirmed-result boundary

v70 keeps identity selection in the matcher and browser/network primitives in the transport layer. After a candidate is confidently selected, the matcher builds the confirmed result directly from complete Algolia metadata (name, rating, ratings count, ABV, canonical URL, plus existing brewery/type metadata). It calls the existing detail-page extractor only when required Algolia result data is incomplete or malformed. This changes result-data authority, not candidate scoring, ambiguity handling, search fallbacks, expansion, or rate-limit behavior.


## v71 transport shadow boundary

The transport layer may issue a bounded, opt-in browser-context replay solely for diagnostics. The matcher receives and trusts the original UI-triggered search response exactly as in v70. This preserves the transport/matching authority boundary while allowing evidence gathering before any future search-trigger authority change.


## v74 live dependency health check

`untap_smoke.py` owns the manual live integration probe. It is intentionally separate from deterministic tests and normal batch execution. Architecture-invariant tests include it explicitly: the smoke layer may depend on matcher, transport, and shared types, but not parser, batch, or Playwright directly. The command `python3 untap.py --smoke-test` exercises one UI bootstrap/template capture followed by one serial authoritative browser-context Algolia search, then validates the confirmed-result contract and known identities without pinning mutable rating values. It does not probe rate-limit thresholds.

The current deployment/operating model is manual/local only. No GitHub automation is part of the project; manual invocation is the authoritative operational path.
# v87 output lifecycle

The CLI reserves a unique local-time timestamp/title directory for each batch run.
It passes explicit paths to the unchanged CSV and HTML serializers. No matcher
policy or result schema changes are involved. CLI CSV naming and resume options
are removed; historical batch resume helpers remain internal and are no longer
reachable through the CLI. Earlier resume descriptions below document history.
Debug remains terminal-only. Publishing accepts the selected run's HTML path.

The standalone `untap_inspect.py` diagnostic reuses the matcher's established
serial, self-healing page-zero search transport and the transport layer's strict
response/query pairing. It deliberately stops before candidate construction,
scoring, expansion, and detail extraction. Its raw hit JSON and derived field
inventory are local observational artifacts ignored by Git.
Optional all-page inspection replays the captured request serially, validates
query/index/page metadata, and observes the existing 20-page safety cap. It is
explicitly diagnostic and does not alter matcher expansion policy.

The matcher retains `alias_alt` on Algolia candidates for a separate debug-only
analysis after final brewery and ABV compatibility filtering. Exact normalized
alias correspondence may be logged as unique or inconclusive evidence, but the
result is not consumed by scoring, ordering, ambiguity, fallback, acceptance, or
presentation. This keeps the field observational until its semantics have been
validated across more real menus.

## Saved-run and review boundaries (v94–v103)

- `untap_snapshot`: lossless JSON persistence and lightweight occurrence-aware menu IDs.
- `untap_identity`: logical title identity shared by registry and publisher; no upward imports.
- `untap_refresh_config` / `untap_registry`: configuration validation and opt-in run registration. Missing sources warn; incomplete runs are rejected.
- `untap_inspect`: explicit read-only Algolia inspection using parser preflight and transport.
- `untap_manual_candidates`: explicit candidate retrieval and URL validation.
- `untap_refresh`: snapshot selection application, fresh output rendering and optional local publication.
- `untap_local_review`: localhost HTTP review and saved-run creation; unexpected errors return JSON.

Dependency tests discover every runtime module and check transitive boundaries. Matching's final identity resolution, HTML card rendering and browser JSON POST mechanics are separate helpers; orchestration retains responsibility for ordering and policy.

## Exact-base qualifier allowlist

`EXACT_BASE_FLAVOR_QUALIFIERS` and `EXACT_BASE_PROCESS_QUALIFIER_RE` preserve the bounded v86 flavor/process extensions observed in regression menus. They serve only the exact-base acceptance rule, not general flavor removal or scoring. Unknown qualifiers fail that rule; expanding the vocabulary requires explicit policy review and matching fixtures. The v103 production/vintage guard is independent: it requires explicit opposite production statuses and a pure trailing vintage on the same brewery/name family and exact ABV. Ratings are not identity evidence.

## Continuation (v104)

`untap_continue.py` owns saved-run preflight, journal recovery and continuation into fresh folders. It calls batch and transport boundaries only for rate-limited/unattempted rows. It preserves saved item IDs and review history. The CLI performs option validation and transport configuration before dispatch. `untap_batch.debug_transcript` shares debug stream handling across normal and continued batches. Input manifests and journals remain until complete final output succeeds; incomplete runs remain publication/registration-blocked.


## Installation boundaries (v105)

The distribution keeps the flat runtime modules and exposes their existing entry points as `untap`, `untap-review`, `untap-refresh`, `untap-publish` and `untap-inspect`. Smoke checks remain an option on `untap`. `untap_version.py` supplies both build metadata and `untap --version`; snapshot schema versioning remains independent.

`untap_assets` holds the review JavaScript. The renderer reads it with `importlib.resources` and embeds the same bytes inline; installed reports remain self-contained. `untap_setup.py` supplies `untap-install-browser`, invoking Playwright with the current interpreter, including inside pipx. The transport diagnoses a missing executable at browser launch, after local preflight; other launch errors retain their original diagnostics. No browser is downloaded implicitly.

Python 3.9 remains the declared and tested minimum. Cwd-relative output defaults, matching, snapshots and report rendering are unchanged. Distribution checks build and install a wheel into a clean environment, exercise entry points outside the checkout and compare deterministic output bytes against the previous release.


## Unified command composition (v106)

`untap_cli.py` owns the installed `untap` command and composes argparse subparsers from each tool's `configure_parser` function. Parsed namespaces flow to the same `run_options` function used by standalone entry points. Search and smoke use the shared intermixed parser to preserve positional/option ordering. Smoke sets the existing smoke flag rather than duplicating fixtures or browser execution.

The dispatcher is above all runtime modules; search, report, registry and transport never import it. Legacy option-led and query forms delegate to `untap.main`, while separate commands and source scripts remain available. A leading exact command word is reserved; `run` or `--` explicitly disambiguates such queries. Local help, validation and offline report operations remain browser-free.

### Conflict inspection evidence

When all retrieved candidates are rejected for ABV or brewery conflicts, the decision retains their ordered evidence and individual exclusion reasons. Finalization projects up to ten into `excluded_candidates` in the saved result. The renderer provides inspection-only links outside candidate cards. Review selection validation reads only selectable alternatives and same-ABV variants, so these links cannot become confirmations. This is an intentional additive output change after the frozen v107/v108 contract; matching outcomes and eligible alternatives remain unchanged.

### Shared run-output serialization

`untap_run_output.py` owns the CSV schema/export and writing an existing snapshot's JSON, HTML and optional CSV into a directory already reserved by its caller. It depends only on shared types, snapshots and the renderer, with no batch, matching, transport or publishing imports. Batch retains CSV-before-HTML ordering and the renderer's current-date behavior. Continuation uses saved report metadata and HTML-before-CSV ordering. Refresh renders before reserving its output directory and passes that HTML to the shared writer. Folder naming, snapshot creation, journals and cleanup remain workflow responsibilities; output failures propagate without removing recovery files. `untap_batch.save_csv` and `CSV_FIELDS` remain compatibility exports.

### Shared review policy

`untap_review_policy.py` owns the selection report fingerprint, review-candidate precedence/order/limits, selectable-candidate lookup, and report row rating order. It is pure and depends only on shared types. The renderer consumes this policy, while refresh and local review import it directly rather than importing private renderer helpers. Excluded inspection links remain ineligible; user-added candidates, stable ties, URL validation and existing report fingerprints are unchanged. Renderer helper names remain compatibility exports for older source callers. Selection mutation and history still belong to refresh; network retrieval and HTML remain outside policy.

### Report card presentation model

`untap_report_model.py` prepares frozen, typed card rows from saved results, including occurrence-aware IDs, display metadata, production labels, review candidates, user-added verification notes, best guesses and excluded inspection links. It depends on types, review policy and snapshot IDs, and contains no HTML or filesystem/browser operations. The renderer retains HTML templates, escaping, URL/asset safety and page/filter markup. A 40-case fixture captured from the pre-extraction renderer checks exact fixed-date HTML hashes, including existing decision cases and production, manual-selection, user-added, escaping and ordering cases. The model is presentation-only and is never persisted in snapshots.
