# HTML report changelog

## v78

- Adds optional descriptive report identity through `--report-title`.
- Uses the descriptive title for the HTML document title and visible report heading; default remains `Untap Results`.
- Rejects missing/empty report titles and `--report-title` without `--html` before browser startup.
- Embeds machine-readable report title, generation date, total count, confirmed count, and needs-review count as HTML metadata for a future archive publisher.
- Keeps confirmed-beer rating ordering, review-candidate match-score ordering, canonical Untappd links, self-contained rendering, and zero-network report generation unchanged.
- Adds no GitHub-specific or publishing behavior to the report layer.

## v77

- Introduces `untap_report.py` as a presentation-only boundary for completed batch results.
- Adds responsive, self-contained `results.html` generation through `--html`.
- Confirmed results sort by Untappd rating descending.
- Needs-review candidates sort by match score descending and remain grouped by uncertain input.
- Confirmed and review-candidate beer names link to canonical Untappd `/b/` URLs when available.
- Uses only standard-library HTML/URL handling plus shared `MatchResult` type contracts; no network, Playwright, parsing, matching, batch, or transport dependency.
