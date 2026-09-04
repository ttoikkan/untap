# HTML report changelog

## v86

- Corrects the v85 aggregate label: failed and other unresolved results are no longer counted as ambiguous in visible summaries.
- Adds optional ambiguous/failed metadata while retaining the legacy aggregate review count.
- Uses a neutral missing-reason fallback for non-ambiguous statuses.

## v85

- Labels unresolved results as `ambiguous` in the visible report summary instead of the potentially misleading phrase `need review`.
- Uses `Match is ambiguous` when an unresolved result unexpectedly has no explanatory reason.
- Keeps embedded review-count metadata, result structure, styling, filtering, sorting, and matching behavior unchanged.

## v84

- Removes the obsolete `margin-bottom` from top-level ambiguous cards; the unified Results list now supplies the same spacing between confirmed and ambiguous cards.
- Displays the matcher-owned sentence-cased ambiguity reasons unchanged.
- Adds no filtering, sorting, candidate-ordering, matching, persistence, network, or publishing behavior.

## v83

- Merges confirmed and ambiguous top-level report cards into one Results list sorted by rating.
- Confirmed cards sort by their own Untappd rating.
- Ambiguous cards sort by the rating of the highest match-score candidate, never by the highest-rated candidate.
- Keeps the existing ambiguous badge, explanation, candidate cards, match-score ordering, and candidate metadata unchanged.
- Places results without a usable sort rating after rated results.
- Keeps style filtering, self-contained inline CSS/JavaScript, canonical links, and embedded summary metadata unchanged.
- Adds no matcher, persistence, network, publishing, or archive behavior.

## v82

- Replaces native style-filter checkbox presentation with rounded selectable chips while keeping real checkbox inputs and existing filtering semantics.
- Uses the report's existing `Canvas`, `CanvasText`, and `LinkText` system colors so the controls continue to blend with the self-contained light/dark-aware report styling.
- Selected chips show a checkmark and accent border/tint; unselected chips remain muted and fully clickable.
- Adds hover and keyboard `:focus-visible` states with a larger touch target than the former native checkbox labels.
- Disables chip transitions when `prefers-reduced-motion: reduce` is active.
- Leaves style-group derivation, filter ordering, checked-by-default behavior, card metadata, Needs review behavior, and inline JavaScript filtering unchanged.
- Adds no external CSS, JavaScript, assets, network requests, persistence, or publishing behavior.

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
# v88

- Adds remote, lazy-loaded beer-label thumbnails from existing Algolia data.
- Allows only HTTPS `assets.untappd.com` images, reserves image dimensions, sends
  no referrer, and hides broken images without hiding report content.
- Adds a status filter that combines with the existing style filters.
- Keeps CSV unchanged and adds no matcher or report-generation requests.
# v89

- Makes thumbnails with valid Untappd HD images keyboard-accessible preview controls.
- Uses a native dialog with explicit, Escape, and backdrop closing plus focus restoration.
- Adds a neutral notice to ambiguous candidates only when Untappd explicitly reports false.
- Keeps missing or unfamiliar production metadata silent and matching-independent.
