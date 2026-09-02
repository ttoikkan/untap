# v86 validation and manual release gate

This branch is pending validation against the user's four saved menus. No live
Untappd run or archived-report replacement is performed by the deterministic suite.

## Matcher policy

- Only a true zero-hit primary search enables the new leading-word retry.
- Remove exactly one leading `On`, only with a separately known brewery and at
  least four remaining name words. Retry once before existing trailing fallbacks.
- Require an exact recovered name, matching meaningful brewery tokens, and exact
  ABV (existing 0.01 tolerance). Score against original input, not corrected text.
- Prefer an already top-ranked exact base name only when all competitors share
  brewery/ABV and extend that name with recognized flavor or process qualifiers.
- Flavor suffixes initially supported: peach, cherry, blueberry, raspberry,
  blackberry, strawberry, marshmallow, orange marmalade, fluff strawberry.
- Process suffixes: double dry hopped, optionally `w`/`with` one of Centennial,
  Citra, Mosaic, Simcoe, Cascade, or Amarillo. This is a deliberately limited
  vocabulary, not beer-ID or brewery-specific exceptions.
- Unknown suffixes, batch/year alternatives, duplicate exact names, missing
  identity evidence, and capped/error/early-stopped expansions block preference.
- No popularity, recent-rating, availability, or style-suffix inference is added.
  M-43 remains outside this release's acceptance changes.

## Reports and archive compatibility

`untap-review-count` still means all non-confirmed results. New reports also emit
`untap-ambiguous-count` and `untap-failed-count`; remaining non-confirmed results
are labeled unresolved. The two optional fields must occur together, be
nonnegative integers, and sum to no more than the review count. Legacy reports
remain valid and are labeled unresolved by the new archive publisher, since
their metadata does not reveal individual statuses. Historical files are not
rewritten automatically. CSV/status schemas remain unchanged.

## Manual checks

Keep the four menus and their v85 CSV/HTML outputs separately. Run each menu on
this branch without resuming old CSV rows, so matching is actually re-evaluated.
Compare canonical beer URLs/IDs and statuses, not changing ratings/counts.

| Case | Expected check |
| --- | --- |
| Hudson Valley / On the Manner of Addressing Clouds / 8.0 / Sour DIPA | Recover beer 2622365 via the one leading-word retry |
| Xül / PB&J Mixtape / 6.5 | Prefer exact base when the full candidate set satisfies the guards |
| Sante Adairius / Tomorrow, Today / 7.4 | Prefer exact base over the explicit DDH Centennial variant |
| Each A Little Token / 5.2 | Preserve ambiguity with Batch 2 |
| Old Nation / M-43 / 6.8 | Preserve current ambiguity and scores |
| Previously confirmed rows | Preserve beer identity |
| Nailo original outcome | Summary breakdown is 15 confirmed, 3 ambiguous, 1 failed before matcher recoveries; totals change after recovery |

Investigate any changed confirmed identity before merging. New unknown variants
may deliberately retain ambiguity; do not broaden qualifiers just to force a pass.
