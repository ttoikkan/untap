# v73

- The matcher-facing page-0 transport wrapper now self-heals one non-429 direct transport failure through a single UI recapture before returning a result.
- 429 continues to bypass recovery and propagate immediately to existing fail-fast batch handling.
- Matching/scoring/ambiguity/fallback semantics are unchanged.
- Adds deterministic tests for successful recovery, bounded failed recovery, and 429 no-recovery behavior.

# v71

- Wires measurement-only transport shadow comparisons into both primary and fallback search attempts.
- Matcher decisions continue to use only the UI-triggered response.

# Matcher changelog

## v86

- Filters clear ABV conflicts after retrieval/recovery and before final matching decisions, so rejected candidates cannot appear in output alternatives or veto exact-base acceptance. Missing/nearby ABVs remain eligible; all-conflict outcomes are explicit and contain no proposed beer link.
- Manual-regression follow-up: recognize a terminal `Beer Company`/`Beer Co.` designation only in exact-base brewery comparison; preserve shared normalization and candidate scores.
- Debug output lists all exact-base candidates and explains acceptance or the first blocking guard.
- Adds bounded zero-hit leading-`On` discovery recovery; returned identity must match the recovered name, brewery, and ABV, with scoring against original input.
- Adds guarded exact-base acceptance over a limited flavor/process suffix vocabulary without altering scores. Unknown, batch/year, duplicate, and incomplete-search cases remain uncertain.
- Keeps 429 fail-fast behavior and defers style-suffix normalization.

## v84

- Sentence-cases the existing user-facing ambiguity reason strings at their source, including near-tie, family, same-ABV, and brewery-like ambiguity wording.
- Keeps the reasons canonical across terminal, CSV, and HTML output without renderer-specific capitalization.
- Changes no scoring, ordering, ambiguity decisions, expansion, fallbacks, or selected identities.

## v80

- Ambiguity candidate projections now preserve the candidate's canonical Untappd `type_name` for downstream report presentation.
- Refactors the repeated compact ambiguity-candidate dictionary into `_alternative_from_candidate()` so `alternatives` and `same_abv_variants` share one projection contract.
- Candidate scoring, ordering, ambiguity decisions, expansion, fallbacks, and selected identities are unchanged.

## v59

- No matcher behavior changes. v59 only extracts batch/CSV/resume responsibilities from `untap.py`.

## v58

- Architecture only: direct Playwright/Algolia transport operations were moved out of `untap_matcher.py` into `untap_untappd.py`.
- Matcher ownership remains candidate scoring, identity verification, ambiguity handling, fallback strategy, ABV-family logic, expansion decisions, and final match selection.
- Search/fallback ordering, scoring constants, ambiguity rules, family logic, and metadata-selection behavior are intentionally unchanged from validated v57.

## v57

- Extracted the existing Untappd matcher from `untap.py` into `untap_matcher.py`.
- Moved matcher configuration/constants, candidate scoring, ambiguity logic, search/fallback construction, Algolia conditional expansion, ABV-family handling, metadata recovery, and `search_one()` without intentional behavioral changes.
- Added pure-function matcher regression tests.

## v56

- No matcher behavior changes. v56 added a parser/preflight boundary before browser startup.

## v60

- No scoring, ambiguity, ABV-family, fallback, search, or acceptance changes.
- Added the explicit `MATCH_RESULT_STATUSES` vocabulary and contract coverage for the stable `search_one()` entry-point signature.
- Removed imports left unused by the earlier transport extraction.

## v62

- No runtime behavior changes in this module. v62 adds project-level reproducible dependency setup and deterministic CI only.

## v63

- Adds a typed `search_one()` public boundary returning `MatchResult` and typed expected identity inputs.
- Adds shared static candidate/result record shapes and a `Literal` status vocabulary aligned by tests with `MATCH_RESULT_STATUSES`.
- No scoring, ambiguity, fallback, search, ABV-family, or acceptance behavior changes.

## v64

- No matcher behavior changes. v64 adds opt-in search-response timing diagnostics in the Untappd transport/CLI path only.

## v65

- No matcher behavior changes. v65 only extends timing instrumentation in the transport and batch layers.

## v66

- No matcher policy changes.
- Adds opt-in phase-level timing around existing matcher operations and a matcher residual/unaccounted measurement.
- `search_one` retains its exact public signature; a thin timing wrapper delegates to the unchanged decision implementation when timing is enabled or disabled.
- No scoring, ambiguity, expansion, fallback-selection, or detail-selection behavior is intentionally changed.

### v66 validation correction
- Annotated `_MATCHER_TIMING_STATS` with a private `_MatcherTimingStats` `TypedDict` so the new measurement-only timing state is accepted by the pinned mypy configuration.
- No matcher behavior changes.

### Corrected v66 build
- Fixed `--debug-timing` fallback instrumentation to use the fallback search query in its timing label instead of an undefined variable.
- Added the existing search-page/search-box readiness operation to the primary matcher timing buckets.

## v67

- Starts from the final corrected v66 matcher, including the fallback-timing NameError correction and completed search-page/fallback timing instrumentation.
- Adds opt-in, shadow-only Algolia-vs-DOM candidate parity instrumentation under `--debug-timing`.
- Builds shadow candidates solely from the already-captured, conservatively validated Algolia page-0 payload.
- Compares candidate identity set/order, normalized name/brewery/ABV fields, and match-score parity.
- DOM candidates remain authoritative; no matcher decision consumes the shadow pool in v67.
- Adds no network requests and makes no scoring, ambiguity, fallback, expansion, or acceptance-policy change.

### v67 parity diagnostic patch
- Field-parity discrepancies now print the exact differing field(s) plus raw DOM and Algolia values for the shared candidate identity.
- This is diagnostics only; candidate authority, scoring, ambiguity, fallback, expansion, and network behavior are unchanged.

## v68
- Captured Algolia page-0 candidates become authoritative for primary and fallback searches after v67 parity validation.
- Removes rendered-DOM candidate scraping from matcher execution.
- Keeps native Algolia ABV precision and richer brewery metadata.
- Retains existing candidate filtering, scoring, ambiguity, fallback, expansion, and detail-page behavior.

## v69
- Adds opt-in shadow comparison of confirmed detail-page values against the already captured authoritative Algolia candidate.
- Independent comparison fields are beer name, rating, ratings count, and ABV.
- Detail-page values remain authoritative; the shadow result cannot change match status, score, ambiguity, fallback, or final output.
- Brewery and `type_name` are explicitly excluded from independent parity claims because current detail extraction does not parse those fields independently.
- No network or matching-policy changes.

## v70
- Promoted complete Algolia selected-candidate metadata to confirmed-result authority after v69 demonstrated 38/38 parity for name, rating, ratings count, and ABV on menu9.
- Detail extraction is now a conservative fallback for incomplete/malformed required Algolia fields.
# v88

- Carries the existing Algolia `beer_label` URL through result presentation data.
- Formats debug candidate scores to three decimals and distinguishes exact-base
  preference rules that are not applicable from those that are not selected.
- Does not change scoring, candidate order, ambiguity, or acceptance policy.
