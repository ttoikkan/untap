# v76

- Adds explicit structural detection and raw validation for brewery-heading blocks (`menu2.txt`).
- Adds explicit structural detection and raw validation for beer/style + ABV/IBU/brewery pairs (`menu3.txt`).
- Adds explicit structural detection and raw validation for tap-list blocks with standalone display ratings and serving-price rows (`menu4.txt`).
- Reuses the established stateful normalization path after validation; no matcher/search heuristics are added.
- Adds the exact three historical inputs as golden regression fixtures and verifies they remain browser-free under `--validate-menu`.

# Parser changelog

## v59

- No parser behavior changes. v59 only extracts batch/CSV/resume responsibilities from `untap.py`.

## v58

- No parser changes. v58 is an Untappd transport-layer extraction.

## v57

- No parser behavior changes.
- The validated v56 parser/preflight contract is preserved unchanged while matcher code is extracted to its own module.

This file tracks changes to `untap_parser.py` and the menu-normalization contract.

## v56

- Added explicit detection of the four documented raw menu formats:
  - tab-separated `brewery<TAB>beer<TAB>ABV<TAB>style`
  - three-line Beer / Style+ABV / Brewery records
  - `Beer // ABV // Style`
  - supported webshop/catalog rows
- Added strict raw-format validation. Once a strong format signal is detected,
  malformed input is rejected instead of being reinterpreted by another parser.
- Added independent validation of normalized parser records before they may be
  handed to the matcher.
- Added `validate_and_parse_menu_lines()` and `read_validated_menu()` as the
  local preflight API.
- Added user-facing detected-format names and validation errors.
- Preserved the approved v55 golden outputs for all four supported formats.

## v55

- Exposed the canonical supported-format help text through
  `supported_formats_help()` and `print_supported_formats()`.
- Made parser regression tests self-contained golden/contract tests; the suite
  no longer depends on `untap_stateful_v52.py`.
- No parser heuristic changes.

## v53-v54 architectural baseline

- Extracted deterministic menu parsing from the monolithic executable into
  `untap_parser.py`.
- Parser remains independent of Playwright, Algolia, HTTP, and Untappd-page
  behavior.
- Normalized record contract:
  `brewery`, `beer`, `style`, `menu_abv`, `query`, `original`.

## v60

- No parsing heuristic or supported-format changes.
- Added the explicit `NORMALIZED_RECORD_FIELDS` contract and reused it in normalized-record validation so the parser-to-runtime boundary has one canonical field definition.
- Added cross-module contract coverage for the normalized record shape and dependency boundary.

## v62

- No runtime behavior changes in this module. v62 adds project-level reproducible dependency setup and deterministic CI only.

## v63

- Adds static typing to the validated parser-output boundary using `NormalizedMenuRecord`.
- Runtime parsing and validation behavior are unchanged; `NORMALIZED_RECORD_FIELDS` remains the runtime source of truth and is contract-tested against the TypedDict field set.

## v64

- No parser behavior changes. v64 adds opt-in search-response timing diagnostics in the Untappd transport/CLI path only.

## v65

- No parser or validation behavior changes.

## v67

- No parser or validation changes.
