# Untap architecture contract

v60 closed the architecture-renewal effort. Later releases preserve that decomposition while hardening and optimizing the established boundaries. v73 hardened the direct search transport and extended static checks. v74 added the separate manual live-dependency smoke boundary and removed unused GitHub workflow automation. v75 consolidated the final validated manual/local-only v74 corrections. v76 expands only the parser/preflight input contract for three structurally clear historical menu layouts. v77 adds a separate static HTML-report presentation boundary. v78 extends only that presentation contract with optional descriptive report titles and archive-oriented HTML metadata; downstream parser, matcher, batch, and transport behavior remains unchanged.

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

The batch layer consumes validated `NormalizedMenuRecord` values or plain query strings and returns `MatchResult` values. It owns iteration, occurrence-aware resume/cache reuse, CSV serialization, and fail-fast handling once a matcher result reports HTTP 429.

The stable CSV order remains `CSV_FIELDS`; v63 adds a corresponding `CsvRow` TypedDict and contract test. Only confirmed `status=ok` rows are reusable.

## HTML report contract (v77–v78)

`untap_report.py` owns static human-facing HTML rendering from already completed `MatchResult` records. It may depend on shared type contracts only; it must not import parser, matcher, batch, transport, smoke, or Playwright layers. The CLI may invoke it after a batch completes.

The report is self-contained and responsive, makes no network requests, and does not alter result data. Confirmed beers are ordered by Untappd rating descending. Ambiguous candidates remain grouped by input result and are ordered by match score descending. Canonical Untappd `/b/` URLs are rendered as links for confirmed beers and review candidates when available. CSV remains the persistence/resume format; HTML is presentation only.

v78 adds an optional descriptive title supplied by the CLI through `--report-title`. The renderer also embeds simple machine-readable metadata for report title, generation date, total beers, confirmed beers, and needs-review count. That metadata is presentation/archive context only; no GitHub or publishing responsibility is introduced into Untap.

## CLI contract

`untap.py` owns argument parsing, menu preflight orchestration, browser-session orchestration, and user-facing presentation. It should not accumulate parser heuristics, matching rules, direct Algolia mechanics, or CSV/resume implementation.

## Static typing rule (v63)

Typing is deliberately incremental and boundary-first. Runtime validators remain authoritative safety checks. New functional work should preserve or improve type coverage at touched module boundaries, but v63 does not require wholesale annotation of internal helpers solely for annotation coverage.

The static checker is pinned in `requirements-dev.txt` and is run manually/local with:

```text
python -m mypy untap_types.py untap_parser.py untap_matcher.py untap_batch.py untap_untappd.py untap_smoke.py untap_report.py untap.py
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
