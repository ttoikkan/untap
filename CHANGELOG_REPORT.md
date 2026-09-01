# HTML report changelog

## v80

- Adds inline checkbox filtering by broad style group while preserving one self-contained static HTML file.
- Style groups are entirely data-derived from canonical Untappd `type_name`; there is no predefined style vocabulary.
- A group is the normalized leading component before the structural `" - "` subtype separator; styles without that separator remain unchanged.
- Only groups present in the report are rendered, in case-insensitive alphabetical order, and all are checked by default.
- Beer cards carry normalized style-group keys while continuing to display the full canonical Untappd style.
- Needs-review candidates display/preserve canonical style metadata and participate in filtering when style data is available.
- The filter script is inline and dependency-free, so archived reports continue to work directly from local disk or GitHub Pages.
- No rating/ABV filters, text search, saved preferences, extra sorting, server state, or publishing changes are included.

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
