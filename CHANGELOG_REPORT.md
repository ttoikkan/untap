# HTML report changelog

## v77

- Introduces `untap_report.py` as a presentation-only boundary for completed batch results.
- Adds responsive, self-contained `results.html` generation through `--html`.
- Confirmed results sort by Untappd rating descending.
- Needs-review candidates sort by match score descending and remain grouped by uncertain input.
- Confirmed and review-candidate beer names link to canonical Untappd `/b/` URLs when available.
- Uses only standard-library HTML/URL handling plus shared `MatchResult` type contracts; no network, Playwright, parsing, matching, batch, or transport dependency.
