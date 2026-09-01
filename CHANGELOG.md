# v79

- Built directly from the validated v78 baseline.
- Adds standalone `untap_publish.py` for local preparation of the public static report archive.
- Validates v78+ embedded report metadata, creates a safe dated archive filename, copies the report into `reports/`, and regenerates `index.html` newest-first.
- Refuses accidental report overwrites and fails closed on malformed source or existing archive reports.
- Archive titles and metadata are HTML-escaped; filenames use a conservative ASCII slug.
- Publisher performs no Git operations, GitHub authentication/API calls, browser automation, or network requests; final `git add`/`commit`/`push` remain explicit user actions.
- `untap.py` and `untap_report.py` do not import the publisher, preserving the report-generation/publishing boundary.
- No parser, matcher, ambiguity, ABV, transport, self-healing, 429, CSV/resume, smoke, pacing, concurrency, performance-policy, or v78 HTML-report changes.
- Deterministic suite: 119 tests.

# v78

- Built directly from the validated v77 baseline.
- Adds optional `--report-title TITLE` for `--html` batch reports.
- The title is rendered in the browser title and report heading; the default remains `Untap Results`.
- Adds archive-oriented HTML metadata for report title, generation date, total beers, confirmed beers, and needs-review beers.
- Invalid/missing report-title arguments fail before Playwright/browser startup.
- Keeps the HTML renderer presentation-only and free of GitHub/publishing/network responsibilities.
- No parser, matcher, ambiguity, ABV, transport, self-healing, 429, CSV/resume, smoke, pacing, concurrency, or performance-policy changes.
- Deterministic suite: 106 tests.

# v77

- Presentation-only release built directly from the validated v76 baseline.
- Adds optional `--html` output for `--menu` and `--file` batch runs; default artifact is `results.html`.
- Adds `untap_report.py`, a self-contained responsive HTML renderer with no parser, matcher, batch, transport, smoke, Playwright, or network dependency.
- Confirmed beers are sorted by Untappd rating descending and link to canonical Untappd `/b/` pages.
- Needs-review ambiguity candidates stay grouped by result, are sorted by match score descending, and link to their own canonical Untappd beer pages when available.
- HTML rendering uses inline CSS only: no JavaScript, external assets, or additional Untappd requests. CSV remains the persistence/resume format.
- Extends architecture-invariant tests to the new report boundary and adds a browser-free invalid-`--html` preflight check.
- Static-validation target expands to all eight runtime modules.
- Deterministic suite: 101 tests.
- No parser, matcher, ambiguity, ABV, transport, self-healing, 429, CSV/resume, smoke, pacing, concurrency, or performance-policy changes.

# v76

- Focused parser-contract expansion from the final validated v75 baseline.
- Restores intentional support for `menu2.txt`, `menu3.txt`, and `menu4.txt` through three narrow structural format adapters.
- Keeps fail-closed behavior for arbitrary unsupported free-form input; `menu.txt` is not added to the supported contract.
- Adds exact golden fixtures plus local/browser-free preflight coverage.
- Deterministic suite: 93 tests.
- No matcher, ambiguity, Algolia transport, self-healing, 429, CSV/resume, smoke, pacing, or performance-policy changes.

# v75

- Consolidates the final validated v74 manual/local-only baseline into one authoritative release artifact.
- Includes the v74 smoke-module architecture-invariant coverage and browser-free invalid-smoke preflight guard.
- Includes removal of the unused `.github/workflows/` configuration and its workflow-pinning tests.
- Corrects the remaining README wording so full mypy coverage is described as **local static validation**, not CI.
- Preserves all v73 `fixed2` transport self-healing and typing corrections.
- No runtime, parser, matcher, ambiguity, transport-authority, smoke behavior, pacing, concurrency, or performance changes.
- Deterministic suite: 89 tests; static-validation target: all seven runtime modules.

# v74

- Built directly from the final validated `v73_fixed2` baseline, preserving v73 self-healing transport behavior and all follow-up mypy fixes.
- Adds `python3 untap.py --smoke-test`, a manual live production integration check for Untappd dependency drift.
- Smoke coverage includes UI bootstrap, Algolia template capture, serial authoritative browser-context transport, confirmed-result response shape, stable identity checks, and explicit HTTP 429 reporting.
- The smoke check never asserts mutable ratings/counts and never probes the rate-limit threshold by generating artificial load.
- Adds machine-usable smoke exit codes for bootstrap/template, direct transport, response-contract, identity, HTTP 429, and runtime failures.
- Adds `untap_smoke.py` to mypy coverage, bringing static checking to all seven runtime modules.
- Removes the unused `.github/workflows/` configuration and its workflow-pinning tests. The current operational model is manual/local only; GitHub automation is not part of the project.
- No parser, matcher, ambiguity, pacing, concurrency, or search-authority policy changes.

# v73

- Adds bounded self-healing for v72's authoritative direct search transport: a non-429 direct failure invalidates the cached Algolia request template and retries the same search once through the established UI path to recapture a fresh template.
- HTTP 429 remains fail-fast and never triggers UI recovery.
- Adds recovery audit counters for UI recovery searches, template invalidations, successful recoveries, and failed recoveries.
- Extends CI mypy coverage from four modules to all six runtime modules, adding `untap_untappd.py` and `untap.py`.
- Adds typed Algolia request/event/search-transport contracts around the live transport boundary.
- No matching, ambiguity, fallback-query, expansion, pacing, retry-loop, parallelism, or confirmed-result policy changes.
- Deterministic suite: 85 tests passed locally.

# v72

- Promotes browser-context Algolia fetch to the authoritative serial search transport after one UI bootstrap search captures the request shape.
- Keeps matcher scoring, ambiguity, fallback queries, expansion, HTTP-429 fail-fast behavior, and Algolia confirmed-result authority unchanged.
- No parallelism, pacing, sleeps, or retries were added.
- Adds transport-source timing/audit counters.

# v71

- Adds an opt-in, bounded **UI vs browser-context Algolia search transport shadow** experiment.
- New CLI: `--shadow-search-transport N` issues at most N additional serial shadow requests.
- The normal UI-triggered search response remains fully authoritative for matching.
- Shadow replay preserves the captured Algolia request parameters and compares page-0 metadata plus ordered matching-relevant hit fields (identity, brewery, ABV, rating, ratings count, type).
- No parallelism, retries, pacing changes, scoring changes, ambiguity changes, fallback changes, or authority changes.
- Shadow requests are deliberately opt-in because they increase request volume and can contribute to HTTP 429 rate limiting during the experiment.
- Adds a transport-shadow summary with exact parity, mismatches, errors, 429s, and shadow-fetch timing.

# Untap changelog

## v69 — detail-page / Algolia field parity shadow instrumentation

- Built from the final corrected v68 baseline, including the exact-query response-listener race fix and Algolia-authoritative candidate discovery.
- Keeps detail-page extraction fully authoritative for final confirmed beer data.
- Under `--debug-timing`, shadow-compares independently available detail-page fields against the already captured Algolia candidate: beer name, rating, ratings count, and ABV.
- Reports per-beer parity/differences and an aggregate `Detail-page / Algolia field parity summary`.
- Does not independently compare brewery or `type_name`, because the current detail extractor receives/recovers those from search metadata rather than parsing them independently from the detail page.
- Adds no requests, retries, sleeps, pacing, matcher shortcuts, scoring changes, or ambiguity changes.
- Adds three deterministic detail/Algolia parity tests.
- Local deterministic suite: 70 tests passed.

Live acceptance target: preserve 38 confirmed + 1 deliberate Populus ambiguity while collecting enough field-parity evidence to decide whether a later release can safely avoid some detail-page visits.

## v68 — captured Algolia candidate discovery becomes authoritative

- Built from the final corrected/patched v67 baseline, including the v66 help, fallback-timing, mypy, and completed timing fixes carried into v67.
- Replaces rendered-DOM search candidate discovery with candidate construction from the already captured Algolia page-0 payload.
- Removes the `DOM candidate discovery` phase from the matcher path; `--debug-timing` now reports `Algolia candidate construction`.
- Makes the same switch for primary and fallback searches.
- Preserves the v67 candidate query-word filter and existing matcher scoring/ambiguity/fallback/expansion logic.
- Preserves native Algolia ABV precision rather than rounding to DOM display precision.
- Retains Algolia brewery metadata when present.
- Adds no network requests and leaves detail-page extraction unchanged.
- Removes v67 shadow-parity runtime reporting because the Algolia pool is now authoritative.
- Adds deterministic v68 tests for native ABV precision, brewery metadata, query filtering, and absence of DOM candidate scraping from the matcher.
- Local deterministic suite: 66 tests passed.

Live acceptance target: menu9 remains 38 confirmed + 1 deliberate Populus ambiguity, including Élixir and all three XTRM fallback cases. Observe request cadence/HTTP 429 separately from matching correctness.

### v68 validation patch — Algolia response-listener race
- Fixed a live-search race in `submit_search()`: the exact Algolia `expect_response()` listener is now armed before `search_box.fill(query)` as well as before Enter.
- Untappd can issue its live Algolia request during field fill; previously that response could arrive before the listener was active, causing a full 10-second timeout even though the request had already completed.
- No new requests, retries, sleeps, matcher-policy changes, or candidate-authority changes.
- Added a transport regression test proving the response listener is active before fill and Enter.

## v70
- Uses the selected Algolia candidate as the authoritative confirmed-result source when name, rating, ratings count, ABV, and URL are complete and valid.
- Skips the confirmed beer detail-page navigation in that normal path.
- Falls back to the existing detail-page extractor if required Algolia result data is missing or malformed.
- Keeps matching, ambiguity, expansion, fallback-search, scoring, and rate-limit behavior unchanged.
- Adds debug-timing counters for Algolia confirmations versus detail-page fallbacks.


### v74 architecture-invariant follow-up

- Added `untap_smoke.py` to the static one-way dependency-graph contract test.
- The smoke layer is explicitly prevented from importing parser, batch, or Playwright directly; matcher, transport, and shared types remain its intended dependencies.
- Extended the browser-free CLI preflight invariant to an invalid `--smoke-test` combination, proving standalone smoke argument validation fails before any Playwright import.
- No live smoke behavior, matcher policy, transport authority, or request cadence changed.
