# Unreleased — Capture validation and finalization hardening

- Reject unsupported live-draft metadata, including synthetic shape annotations, while preserving response-shape error precedence. Promote only the five supported corpus fields.
- Return a reviewable low-confidence result when a selected beer has no usable URL, preserving its name and bid diagnostic without navigating. Add a strict replay regression that checks the reason as well as the status and missing URL.

- Split structural response failures from unavailable confirmation metadata. Smoke diagnostics locate incomplete hits by result/hit index and bid; malformed present types remain failures.

# v112 — Capture safeguards, compatibility exports and live replay (2026-10-13)

- Declare intentional compatibility exports in report, batch and run, and test their declaration and implementation identity. The unused-import guard is explicitly a lightweight check of top-level imports, not a scope-aware general linter.
- Add offline corpus recording/sanitization and strict finalization tools. Preserve paging and identity fields, mask ratings without changing None/zero/positive distinctions, and check the allowlist against runtime consumers.
- Share fail-closed validation between recording and edited-draft promotion. Reject every non-200/429 response and shape failure, retain malformed response statuses, prevent further traffic after refusal, and clean up listeners/state on failed flows.
- Replay complete captured UI batches while preserving queryless entries and detecting typed-query mismatches. Require explicit recognized status expectations and reject unknown expectation fields and unsanitized edited payloads.
- Add the trailing-relaxation identity corpus fixture and regression tests for the reviewed capture gaps.
- Add three sanitized live captures and navigation-time empty-query bootstrap replay. Guard bootstrap order, typed-query mismatches and exact-match expansion suppression.
- A live expansion capture was refused for invalid `beer_slug` data; real expansion and retired-base examples remain pending.
- Validation: 412 tests pass (6 installed-wheel checks skipped); 35 source/tooling files type-check. The safeguards previously passed fresh installed-wheel checks and six deliberate regression mutations; frozen report/output checks pass.

# v111 — Search corpus, brewery policy and package migration (2026-10-13)

- Add strict replay at the Playwright I/O boundary, with sanitized hand-authored response-shaped fixtures and a passive smoke response-shape canary. Run request building, decoding, candidates, expansion and decisions for real; reject unexpected and unused exchanges.
- Centralize brewery compatibility and rejection reasons in a pure policy. Retain recovery adoption gates and decision eligibility consequences, including S1 inspection links and S7 primary-evidence retention.
- Split fallback retrieval/filtering and candidate adoption into named helpers; preserve request order, filters, timing, debug and HTTP 429 behavior. Replace assertion-only phase checks with explicit errors.
- Move runtime modules and assets into `untap/`, update imports and package dependency checks, add `python3 -m untap`, and preserve installed commands and historical source/module entry points with thin wrappers. Update current documentation and type-check commands.
- Live validation: maintainer reports no unusual behavior after testing the changes.
- Validation: all 374 tests pass including fresh installed-wheel checks; 34 package/wrapper source files type-check. All 40 frozen HTML reports retain their bytes, installed CSV/JSON/HTML match source output, and 10,000 seeded invariant cases pass. Corpus replay kills removal of the brewery gate, zero-hit gate and conditional expansion. No live service traffic was sent.

## Fallback inspection evidence and CSV safety

- Carry rejected beer-only fallback brewery candidates as inspection evidence while retaining the existing eligibility filter and fallback adoption rules. Report brewery conflicts when none survive; links remain non-selectable.
- Guard winning-fallback metadata pairing and zero-hit expansion behavior. Add a regression where a conflicting fallback must not replace a weak correct-brewery primary result.
- Prefix formula-leading CSV text cells with an apostrophe, preserving numeric values and JSON/HTML data. Cover all protected prefixes and derived candidate-list cells.
- Validation: all 367 tests pass, including fresh installed-wheel checks; all 25 source files type-check. Brewery-filter debug output is preserved, and existing frozen request/output contracts pass. No live Untappd traffic was sent.

## Test directory organization

- Move test modules and their unchanged fixtures into `tests/`, with package-qualified cross-test imports.
- Clarify batch-only output folders and registration requirements; use a fresh wheel-validation directory and unified menu-format examples.
- Consolidate `ARCHITECTURE.md` around current v110 ownership, dependencies and search phases; replace superseded transport, CSV, debug and resume descriptions with current contracts.
- Update source-root paths and documented discovery/invariant commands. Runtime modules, packaging and output behavior are unchanged.
- Validation: both default and explicit test discovery collect all 355 tests; installed-wheel checks pass. All seven moved fixture files remain byte-identical, and the package-qualified invariant command passes.

# v110 — Shared output, report model and explicit search phases (2026-10-12)

- Centralize saved-snapshot JSON/HTML/optional CSV output in an offline module, preserving save order, metadata, recovery handling and compatibility exports.
- Extract pure shared review policy for fingerprints, row order and selectable candidates; remove validators' dependence on private renderer helpers.
- Prepare report cards through a typed, HTML-free presentation model. Preserve templates, escaping, asset safety, labels and saved schemas; 40 pre-extraction reports remain byte-identical.
- Split search orchestration into primary retrieval, conditional expansion and fallback recovery ahead of existing decision/finalization. Preserve request order, fallback gates, identity filters, paging, metadata pairing, debug/timing boundaries and HTTP 429 termination.
- Freeze nine search request/outcome scenarios and add output, presentation, review-policy and phase-metadata regressions.
- Live validation: maintainer confirms each extraction behaves as before.
- Validation: all 355 tests pass, including fresh installed-wheel checks; all 25 source files type-check. Frozen output and request-sequence contracts pass.

# v109 — Review evidence and maintenance (2026-10-12)

- Preserve ABV and brewery conflict candidates as inspection-only report links with exclusion reasons, separately from selectable alternatives. Matching decisions remain unchanged.
- Add an always-on packaging module-list check and whole-chain invariants for minimum score and same-ABV families.
- Point incomplete-run guidance to `untap run --continue`.
- Organize the README by task, mark per-module changelogs as historical, and remove unused imports.
- Live validation: maintainer confirms behavior works as before.
- Validation: all 336 tests pass, including fresh installed-wheel checks; all 22 source files type-check. Default and 10,000-case invariants pass. Offline Chromium confirms inspection links remain non-selectable and the review script initializes without errors.

# v108 — Pure decision stage (2026-10-12; v107 baseline)

- Characterize 24 v107 rule interactions before extraction, preserving full results, debug messages, counter deltas and fixed-date HTML/CSV/JSON bytes.
- Add typed expected/discovery records and an internal `Decision`; extract pure `decide_candidates` in the matcher without changing scoring, ranking, tie order, retrieval or saved schemas.
- Keep captured metadata recovery, detail validation, timing/counters and result construction in finalization. Return diagnostics as data rather than printing or invoking callbacks in the decision stage.
- Add deterministic whole-chain invariants with real scoring, directed interaction cases, coherent discovery context, configurable seed/count and failure shrinking. Incomplete discovery cannot select; selected identities remain provisional until finalization.
- Document precedence, purity boundaries and the scoped distractor/tie properties. Keep explanations and serialized rule names out of this extraction.
- Validation: original 320 tests unchanged; full suite now has 328 tests. Default 2,000-case and alternate-seed 10,000-case invariants pass; all 22 runtime source files type-check. Maintainer reports the live test works.

# v107 — Matching integrity and recovery corrections (2026-10-11)

- Reject explicitly conflicting breweries at final acceptance while preserving unknown metadata and the existing collaboration policy.
- Keep incomplete or early-stopped searches unresolved, with warnings and retrieved candidates available for review.
- Validate detail-page HTTP status, selected beer URL and heading before confirmation. Detail HTTP 429 stops the batch; valid unrated beers remain supported.
- Pair Algolia results with their matching query and validate page/index in ordinary and sorted expansion and inspection.
- Recover completed journal rows when the unterminated tail contains damaged UTF-8; reject damaged complete records. Recover truncated UTF-8 final snapshots through the manifest/journal too.
- Keep missing-browser failures recoverable in local review, with installation guidance retained at CLI boundaries.
- Bound browser POST and response-body reading to 10 seconds, with abort and timer cleanup.
- Restore bounded shadow comparisons for successful UI bootstrap/recovery captures. Replay candidates never affect matching; replay HTTP 429 stops further traffic.
- Live validation: user reports that live tests passed.
- Validation: 21 new behavioral regressions; all 320 tests pass, including a freshly built installed wheel. All 22 source files type-check. An offline Chromium check verifies fetch/body timeouts and timer cleanup. No live Untappd traffic was sent.

# v106 — Unified command interface (2026-10-11)

- Add `untap run`, `review`, `refresh`, `publish`, `inspect` and `smoke` using shared argument definitions and execution functions.
- Retain legacy searches, separate commands and source scripts without deprecation warnings; support explicit `run` or `--` for queries beginning with reserved command words.
- Preserve intermixed search options, local preflight, live smoke exit codes, output locations and matching/report behavior.
- Live validation: installed command processed the 45-row Taproom Tripla menu with 45 confirmed matches; local preview and review tested.
- Validation: all 299 tests pass, including installed-wheel command equivalence; all 22 Python source files type-check. Fixed HTML, CSV and JSON remain byte-identical to v104.

# v105 — Installable command-line tools (included in v106)

- Add Python 3.9+ packaging and installed commands for the existing entry points, keeping source scripts supported.
- Bundle the unchanged review JavaScript in `untap_assets` and load it through the resource API.
- Add `untap --version`, with one version source shared by distribution metadata and the CLI.
- Add `untap-install-browser` for Chromium installation in Untap's environment, and a clear missing-browser message when a search starts.
- Preserve matching, output locations and deterministic HTML, CSV and JSON contents.
- Validation: 286 tests including clean installed-wheel checks; all 21 Python source files type-check. Installed output bytes match fixed v104 references; source distributions also build successfully.

# v104 — Continue unfinished runs (2026-10-11)

- Remove the partial journal and input manifest only after a complete run's HTML/JSON and optional CSV save successfully. Retain both after interruption, rate limiting or save failure.
- Add `--continue RUN` to search only rate-limited and unattempted rows into a new sibling folder. Preserve completed results, input identities, manual decisions, candidate additions and report title; never overwrite the source.
- Recover abrupt shutdowns from a full input manifest plus flushed per-result journal. Support legacy v103 journals with the exact original TSV via `--recovery-menu`; validate row identities and reject malformed data before browser startup.

- Validation: 277 deterministic tests and all 18 runtime module type checks pass, including repeated rate limits, interruptions, crash recovery, source preservation and cleanup after successful saves.

# v103 — Run integrity and maintenance (2026-10-11)

- Require manual review when a yearless menu’s unique exact name/brewery/ABV match is explicitly retired and a pure vintage-qualified same-brewery, same-ABV sibling is explicitly current. Unknown production statuses and rating counts do not decide identity. Name the existing bounded exact-base flavor/process vocabulary without expanding it.

- Isolate shared logical report identity from publishing and verify transitive dependencies across all runtime modules. Consolidate browser JSON POST handling; separate primary diagnostics, final identity resolution and report-card rendering from orchestration. Replace source-spelling assertions with behavior checks and AST dependency rules. Refresh format, architecture and parser documentation.

- Fix review persistence without Web Crypto when an embedded report ID exists, return JSON 500 for unexpected review errors, and validate the local script injection marker. Create reviewed folders with normal directory permissions.
- Share lightweight occurrence-aware item-ID generation between snapshots and HTML; repeated references to one result receive distinct IDs. Preserve raw TSV tabs, clarify empty-style input and reject ABV precision beyond two decimals. Forward stdout encoding/isatty/fileno in debug mode.
- Remove obsolete DOM discovery and CSV-resume machinery, unreachable manual-label logic and unused imports/locals.

- Preserve brewery names unless the normalized beer name contains the complete brewery token sequence. Skip missing refresh registry sources with a warning, leaving their entries unchanged.
- Journal completed batch rows to flushed `results.partial.jsonl` and save full-menu JSON/HTML in a finally block on interruption. Unfinished rows remain explicitly unattempted; abrupt process termination leaves the journal available.
- Update static-check commands to cover all 17 runtime modules. Keep Python 3.9, which supports the tests’ parenthesized with syntax.

- Use argparse for search CLI options, reject unknown/abbreviated flags and positional text alongside menu/file input, and document `--csv` as a boolean export flag. Invalid option syntax exits before search or output creation.

- Preserve all menu rows after HTTP 429 with `not_attempted` results retaining the input identity. Reports explicitly warn that the run is incomplete; publishing and refresh registration reject incomplete runs, including legacy snapshots with a rate-limit remainder count.
- Manual selection changes clear stale IBU, search text, fallback and best-guess fields and normalize selected ABV to a percentage string. Original data remains in decision history.

- Validation: 267 deterministic tests, all 17 module type checks and browser selection/export checks pass.

# v102 — TSV input and optional CSV export (2026-10-11)

- Replace legacy menu adapters and format detection with one strict four-column TSV reader (brewery, beer, percentage ABV, style). Preserve the TSV golden records, matcher text normalization, collaboration handling, decimal commas, zero ABV and name punctuation. Ignore blank lines and accept an optional header and UTF-8 BOM.
- Reject malformed and obsolete menu layouts locally with line-numbered conversion guidance before searching. Require brewery, beer and ABV; allow an empty style.
- Save HTML and JSON by default for batch runs and reviewed/refresh outputs. Make CSV opt-in with `--csv` for search, refresh (including batch refresh) and local review. Keep `--html` compatible and allow report titles directly with batch input.

- Validation: 248 offline tests and type checks passed. TSV golden records are unchanged; output checks cover automatic HTML/JSON and opt-in CSV for searches, refreshes and local review.

# v101 — Exact identities and Change selection (2026-10-11)

- Retain automatic-match alternatives and offer Change selection, with the automatic choice highlighted and Cancel available. Manual changes use the existing reviewed HTML, CSV and JSON workflow.

- After complete discovery, confirm the sole candidate matching the explicit menu name, brewery and ABV, regardless of ranking or other candidates' name qualifiers. Scores and search queries are unchanged.
- Differently named vintage, batch and ingredient variants no longer veto the unique exact identity. This intentionally resolves Boston Lager and the exact Imprint name as well as Broccoli World and Ghost In The Machine.
- Keep competing matches on all three identifiers, incomplete metadata that could hide another exact match, incomplete searches and review-only recoveries uncertain. Existing normalization and exact-ABV tolerance apply.
- Add deterministic Tripla cans regressions for the two confirmed beer IDs and safety guards.

- Validation: 253 offline tests, type checks and browser change/cancel checks passed. User confirmed the Tripla cans v101 live run and Change selection work correctly.

# v100 — Explicit series-number matching (2026-10-08)

- Prefer a unique exact numbered beer name over otherwise identical differently numbered siblings, with matching brewery and exact ABV. Limited to terminal series numbers 1–999; scores and search queries are unchanged.
- Preserve uncertainty for missing series numbers, duplicate exact names, added qualifiers, conflicting metadata, incomplete searches and review-only recoveries. Year handling is unchanged.
- Add Banishing 3 regressions based on the October CM Pirkkala menu.
- User-confirmed live verification: Banishing 3 now resolves correctly in the Pirkkala run.

# v99 — Guarded matching recovery (2026-09-30)

- Expand standalone DDH to Double Dry Hopped for scoring without changing search or display text; retain hop and vintage distinctions.
- Retain bounded XTRM Turbo fallback candidates with additional name tokens for manual review when brewery and exact menu ABV agree. These candidates cannot be automatically confirmed.
- Add offline October-menu regressions for Fort Point, the Bas-Canada/Fidens collaborations, Boston Lager, Imprint and the Humble Sea ABV conflict.
- Keep the Imprint inserted-Apricot variant manual: the existing exact-base rule recognizes suffixes, not inserted ingredients.
- Live Pien regression: 30 confirmed, 2 ambiguous, 0 failed (previously 29/2/1); only Fort Point and Fidens changed match status or selected URL. CM Ruoholahti was not live-retested for this release; its targeted cases are covered by offline regressions.

# v98 — Local browser review (2026-09-21)

- Show the original menu ABV explicitly above ambiguous and failed candidates, separately from Untappd values.
- Harmonize menu ABV and ambiguity-reason typography and spacing.
- Add a one-run loopback review session with explicit candidate fetching and browser-driven saving, without export/import.
- Reuse exact-ID candidate retrieval and snapshot validation; save separate HTML/CSV/JSON runs without publication or source edits.
- Keep published report controls unchanged and restrict local actions with host, origin, token and request-size checks.

# v97 — User-added Untappd candidates (2026-09-09)

- Add per-item pending Untappd URLs in failed/ambiguous report cards, with browser storage and export/import.
- Add explicit --fetch-candidates during selection refresh, requiring exact beer-ID retrieval through existing search transport.
- Preserve original results in candidate-addition history; render unscored user-added candidates for a separate manual confirmation step.

# v96 — Guarded name recovery and brewery verification (2026-09-09)

- Recover extra leading The combined with a short trailing parenthetical annotation after zero hits (Mangolorian & Grogu); require recovered name, brewery and explicit ABV agreement and retain original-input scoring. Numeric annotations are excluded.

- Reject explicitly unrelated short brewery names in beer-only recovery instead of treating them as missing identity; regression covers To Øl versus the Emporium collaboration.

- After zero primary hits, try removing one interior capital I that may represent a misread vertical-bar separator, requiring at least two words on each side and a known brewery.
- Verify recovered name, brewery and explicit ABV; preserve original-input scoring and normal searches.

# v95 — Automatic menu registration and refresh defaults (2026-09-08)

- Support explicit archive/replace configuration defaults, with per-report overrides and inheritance for newly registered menus.

- Add opt-in --register-refresh CONFIG for registering new batch menus after outputs are saved.
- Preserve existing menu entries and never infer publication or selection settings.

# v94 — Offline refresh and reviewed reports

- Save versioned results.json snapshots with full results, report metadata, occurrence-aware menu IDs, and a reserved manual-decision list.
- Preserve candidate metadata omitted from CSV for future offline regeneration; reject unsupported snapshot versions and refuse snapshot overwrites.
- Add offline single-run refresh into a new folder, with optional local archive publication and explicit replacement preserving public URLs.
- Apply snapshot-bound exports with --selections, retaining original ambiguous results in decision history and marking confirmed choices in HTML.
- Add --batch configuration for sequential offline refresh/publication with configuration-relative paths, per-run failure isolation, and a success/failure summary.
- Preserve change-selection and import/export controls in reports with applied manual decisions.
- Older browser-fingerprint exports require refreshing the report and exporting again before offline application.

# v93 — Personal review in reports (2026-09-07)

- Import exported selections after validating the report fingerprint and every candidate; preserve choices for rows absent from the import.
- Accept run directories in the publisher, resolving only their results.html with existing replacement safeguards.

- Embed personal review controls in generated HTML reports, including published reports; no separate review-copy command is required.
- Allow reversible manual confirmation of ambiguous candidates, updating visible counts and ordering by the selected beer's rating.
- Preserve choices in browser storage when available, scoped by report fingerprint and row, and export a JSON record of selections.
- Mark candidates already confirmed for another menu item with an informational “Already matched” tag; do not change scores or prevent selection.
- Use compact manual-confirmation tags and equal-height candidate rows within ambiguity groups.
- Keep choices personal to each visitor's browser; exports are not yet CLI inputs, and shared HTML, CSV, archive counts, and matching decisions remain unchanged.

# v92 — Report card visual refinements (2026-09-06)

- Use consistent thumbnail sizes and rating/count columns across confirmed and ambiguous cards.
- Place candidate match confidence beside the beer name in a separate label.
- Separate brewery and ABV/style lines, reduce production-note emphasis, and refine spacing, borders, and link focus styling.
- Preserve matching and report ordering. Validated with 202 offline tests and manual visual review.

# v86

- Excludes candidates differing from explicit menu ABV by at least the existing 1.0 percentage-point mismatch threshold before final acceptance/ambiguity; keeps rejection diagnostics and returns an explicit failed ABV-conflict result if none survive.
- Adds one brewery-qualified leading-`On` recovery query after a zero-hit primary search, preserving original-input scoring and strict recovered identity/ABV checks.
- Adds guarded exact-base-name preference over recognized flavor/process extensions; preserves scores and batch/year, unknown-qualifier, and incomplete-search uncertainty.
- Splits visible ambiguous/failed/other unresolved counts, with optional backward-compatible archive metadata. Legacy archive entries are labeled unresolved.
- Adds offline matcher orchestration and report metadata regression tests; four-menu manual validation remains a release gate.
- Defers M-43 style-suffix normalization. No parser, CSV/resume schema, transport authority, rate-limit, or publication-safety changes.

# v85

- Replaces the potentially misleading visible summary phrase `need review` with `ambiguous` in HTML reports and archive index cards.
- Changes the rare missing-reason fallback from `Review required` to `Match is ambiguous`.
- Preserves internal `review_count` fields, `untap-review-count` metadata, CSS classes, CSV contracts, and historical changelog terminology for compatibility and accuracy.
- Updates presentation regression coverage for the new wording.
- Deterministic suite: 141 tests.
- No matching decisions, parser behavior, ABV handling, Algolia transport, CSV/resume semantics, publishing safety, smoke behavior, pacing, concurrency, or performance-policy changes.

# v84

- Harmonizes the generated archive `index.html` with the reports' responsive, adaptive light/dark visual language while keeping it self-contained and JavaScript-free.
- Removes the legacy extra bottom margin from ambiguous report cards so the unified Results list owns all top-level card spacing.
- Sentence-cases canonical matcher ambiguity reasons at their source, keeping terminal, CSV, and HTML wording consistent without renderer-specific transformations.
- Adds focused archive-style, report-spacing, and matcher-prose regression coverage.
- Deterministic suite: 140 tests.
- No matching decisions, parser behavior, ABV handling, Algolia transport, CSV/resume semantics, publishing safety, smoke behavior, pacing, concurrency, or performance-policy changes.

# v83

- Built directly from the validated v82 baseline.
- Replaces separate Confirmed and Needs review report sections with one rating-sorted Results list.
- Confirmed results use their own Untappd rating as the top-level sort value.
- Ambiguous results use the Untappd rating of their highest match-score candidate as the top-level sort value; lower-scoring candidates never influence placement even when they have a higher beer rating.
- Preserves the existing ambiguous-card presentation, ambiguity explanations, candidate match-score ordering, candidate details, style filtering, canonical links, and embedded confirmed/review metadata counts.
- Results without a usable sort rating appear after rated results.
- No matcher, parser, ambiguity decision, ABV, transport, CSV/resume, publisher, archive identity, smoke, pacing, concurrency, or rate-limit behavior changes.
- Deterministic suite: 137 tests in this release artifact.

# v82

- Built directly from the validated v81 baseline.
- Replaces browser-native style-filter checkbox presentation with rounded selectable chips in generated HTML reports.
- Keeps semantic checkbox inputs underneath the chip labels, preserving keyboard operation and the existing dependency-free filtering JavaScript.
- Selected chips use the report link accent for border, tint, and checkmark; unselected chips remain visible with muted styling and the entire chip is clickable.
- Adds hover and `:focus-visible` treatment plus a `prefers-reduced-motion` fallback for chip transitions.
- Preserves data-derived style grouping, alphabetical ordering, checked-by-default state, detailed Untappd styles, and Needs review filtering exactly as in v80/v81.
- No matcher, parser, ambiguity, ABV, transport, CSV/resume, publisher, archive identity, smoke, pacing, concurrency, or rate-limit behavior changes.
- Deterministic suite: 136 tests in this release artifact.

# v81

- Built directly from the validated v80 baseline.
- Adds explicit `--replace` support to `untap_publish.py` for intentionally regenerated reports with the same logical descriptive-title identity, independent of generation date.
- Preserves refusal-to-replace as the default behavior; replacement never occurs without the explicit flag.
- Preserves the existing archived filename during replacement so public report URLs remain stable; validates the source and all existing reports first, regenerates the index without duplicate entries, and restores the previous report if index writing fails.
- Fails closed on multiple existing normalized-title matches and never uses `--replace` to overwrite a filename collision belonging to a different title.
- `--replace` on a not-yet-existing logical title behaves as a normal new publication.
- Replacement remains local-filesystem-only; Git, GitHub credentials/APIs, GitHub Pages deployment, and network behavior remain outside Untap.
- No matcher, parser, ambiguity, ABV, transport, CSV/resume, report style-filtering, smoke, pacing, concurrency, or rate-limit behavior changes.
- Deterministic suite: 135 tests in this release artifact.

# v80

- Built directly from the validated v79 baseline.
- Adds self-contained client-side style filtering to generated HTML reports.
- Derives filter groups only from canonical Untappd `type_name` values present in each report; Untap has no predefined style-group taxonomy.
- Uses the leading style component before Untappd's structural `" - "` subtype separator, preserving the full detailed style on each beer card.
- Renders only present style groups, sorted case-insensitively alphabetically, with every checkbox enabled by default.
- Filtering works from a locally opened static `.html` file with inline JavaScript and no server, external JavaScript, CSS, or network dependency.
- Preserves canonical style metadata on ambiguity candidates so Needs review beers can participate in the same filter UI.
- Leaves matching/scoring/ambiguity decisions, parser behavior, ABV policy, transport, CSV/resume, v79 publishing, Git/GitHub behavior, pacing, and rate-limit behavior unchanged.
- Deterministic suite: 128 tests in this release artifact.

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
# v87 — Per-run output folders

- Batch runs reserve unique timestamp/title folders beneath `results/`, preserving previous runs.
- CSV and optional HTML share the folder; completion prints its absolute path.
- Remove CLI `--csv` and `--resume`; reject obsolete flags with migration guidance.
- Every batch searches the full input. Matching and report contents are unchanged.
- Update publishing examples and add offline output-lifecycle regression tests.
# v88 — Visual reports and clearer diagnostics

- Display lazy remote Untappd label thumbnails on confirmed and ambiguous cards.
- Restrict image rendering to HTTPS `assets.untappd.com` URLs and degrade cleanly.
- Add an independent All results / Ambiguous / Failed report filter.
- Save incrementally flushed batch diagnostics as `debug.txt` when `--debug` is used.
- Clarify exact-base diagnostics, format displayed scores to three decimals, and split terminal status counts.
- Preserve matching scores, decisions, request counts, CSV schema, and non-debug behavior.
# v89 — Production context and HD label previews

- Open available Untappd HD label images from report thumbnails in an accessible dialog.
- Fetch the HD image only when requested and retain a plain thumbnail when unavailable.
- Show “Listed as out of production on Untappd” on ambiguous candidates only for explicit false values.
- Keep confirmed cards and true, missing, or unfamiliar values silent.
- Preserve request counts, scores, ordering, confirmation, and CSV schema.
# v91 — Search inspection and diagnostics (2026-09-06)

Validated with 202 offline tests and mypy, plus manual CM Ruoholahti,
Musta Kynnys, Nailo, CM Pirkkala, Konttori, and Mallaskellari runs.

## Search completeness and Konttori regression diagnostics

- Preserve search-cap, expansion-error, and ambiguity early-stop warnings
  separately from ambiguity reasons in HTML and batch terminal output.
- Add debug-only stout/IPA contradiction observations without changing matching.
- Add offline Dragon's Milk, Just Fruit, and Messorem numbered-name fixtures.
- Keep confirmation policy, request limits, and CSV schema unchanged.

## Algolia inspection and alias diagnostics

- Add a standalone read-only inspector for a query, query file, or validated menu.
- Save exact page-zero hit dictionaries as JSON plus a field/type/presence summary.
- Reuse the established serial self-healing search transport without matching,
  scoring, expansion, detail-page requests, or policy changes.
- Stop on HTTP 429 and keep inspection artifacts outside version control.
- Add explicit `--all-pages` inspection with serial requests, pagination
  validation, and a 20-page cap; retain page zero as the default.
- Correct the summary heading so it describes both page-zero and all-page runs.
- Preserve Algolia `alias_alt` metadata in internal candidates and report exact
  alias support under `--debug` only after brewery and ABV compatibility checks.
- Compare aliases with the menu beer and beer-plus-style forms, including a
  narrow letter/number punctuation normalization such as `M-43` → `m43`.
- Keep alias evidence strictly observational: it cannot affect candidate scores,
  ordering, ambiguity, confirmation, fallback selection, or report contents.

# v90 — Consistent production-status rows

- Show explicit in-production and out-of-production Untappd states on confirmed
  beer cards and ambiguous candidate cards.
- Reserve the same silent row for missing or unfamiliar values to align card heights.
- Keep production metadata independent of matching, scores, ordering, and CSV.
