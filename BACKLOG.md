# Backlog

## ABV zero versus unknown

Keep the current conservative interpretation: numeric `beer_abv: 0` is known 0%, so it conflicts with a nonzero menu ABV and remains inspection-only. The live Boston Lager capture includes Barrel Aged Boston Lager at 0%, but this does not establish an upstream unknown-value convention. Before changing policy, obtain evidence that distinguishes missing ABV from genuine non-alcoholic beer; avoid globally converting zero to unknown.


Verified paired examples (2026-10-14):

- [Beerium BFG 2026](https://untappd.com/b/beerium-beerium-bfg-2026/6857122), bid 6857122: detail page shows `N/A ABV`; Algolia search returns `beer_abv: 0`.
- [Heineken 0.0](https://untappd.com/b/heineken-heineken-0-0/1977303), bid 1977303: detail page shows `0% ABV`; Algolia search returns `beer_abv: 0`.

These confirm that the search field alone cannot distinguish unknown ABV from genuine zero. A possible future policy is to inspect the detail page when search ABV is zero but the menu lists a nonzero ABV: treat explicit N/A as unknown while preserving a genuine zero conflict. This requires additional requests and paired regression tests; current behavior remains conservative.

## Real production-guard example

Capture a retired exact-name match beside a current same-ABV vintage sibling when encountered during normal use. The existing real Boston Lager case has a current exact match and a retired dated release, so it does not reproduce this guard. Retain the synthetic regression; do not manufacture a live example or probe rate limits to obtain one.

## Decision result ownership

Clarify whether returned decisions must remain independent of later mutations to input candidates before adding alias-isolation tests or removing defensive copies. Current non-mutation tests establish that calls preserve inputs, which is a separate contract. The review comment on this point was truncated.

## Mutation script anchors

The external mutation script reportedly continues after `PATTERN NOT FOUND`. Its location is pending. Once available, require exactly one anchor match and fail before running a mutant otherwise.

## Cyrillic-only name matching — low priority

Matching normalization currently removes Cyrillic characters rather than transliterating them; original names remain intact in saved/displayed results. Mixed names such as [Lvivske Rizdvyane (Львівське Різдвяне)](https://untappd.com/b/carlsberg-ukraine-lvivske-rizdvyane-lvivske-rizdvyane/290286) work through their Latin spelling. Cyrillic-only menu names lose name evidence, while brewery and ABV evidence can still contribute to a match. Use Latin menu spellings for now. If needed later, evaluate Unicode-aware matching and transliteration with regressions for Cyrillic-only, mixed-script and distinct-name cases before changing normalization.
