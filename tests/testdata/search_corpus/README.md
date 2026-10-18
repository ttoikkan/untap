# Search replay corpus

Most of these are hand-authored, sanitized payload-shaped fixtures; the `live_*` cases are sanitized real captures (see "Capturing real cases"). They exercise the real search flow by replacing only the Playwright page. `tests/replay_page.py` supplies UI bootstrap events and direct fetch responses. No matcher, request-builder, parser or fallback helper is patched.

Each JSON case declares search arguments, an ordered list of exchanges, expected result fields and excluded inspection URLs. An exchange specifies UI or fetch transport and every index/parameter in the POST body, plus the status and minimal Algolia response. Unexpected requests, wrong parameters, unused exchanges, unintended navigation and leaked listeners fail even if production exception handling catches the original replay error. Transport authority state resets for each case.

S1 pins conflicting beer-only inspection links. S7 uses real scores and a stricter threshold to pin retention of a weak compatible primary candidate: a stronger conflicting fallback must not replace it. The trailing-identity case pins rejection of a differently named beer returned by relaxed searches. Other cases cover winning-fallback metadata, page-zero reuse/conditional expansion, an unusable zero-hit page, and immediate 429 termination at bootstrap, fallback and expansion.

To add a recording, remove headers, keys, cookies and unrelated hit fields. Retain request query/page/index/parameters and only fields consumed by response validation, candidate construction and matching. Declare actual capture provenance; hand-authored rare-condition cases must say so. Do not copy whole third-party responses into the repository.

Run `python3 -B -m unittest tests.test_untap_corpus`. The passive smoke shape canary uses `algolia_response_shape_issues` in `untap.transport`; corpus tests keep its required-field expectations aligned. Optional additions are allowed. Hand-authored cases that intentionally omit required identity or paging fields declare the expected structural failures in `shape_issues`. Missing optional confirmation metadata (slug, ratings or style) is diagnostic rather than a structural failure and needs no such annotation. Live drafts never accept `shape_issues` annotations; required-field or malformed-type failures refuse promotion.

## Capturing real cases

Real captures validate our assumptions about actual responses. They use live traffic, so keep them few and deliberate: one run per case, never in a loop, and **never for HTTP 429** (rate-limit cases stay synthetic and are not provoked).

1. `python3 -m tests.corpus_tools record NAME --brewery B --beer N --abv X [--style S]` runs the real flow once and writes `NAME.json.draft`. Every response the flow requested is recorded in order (primary search, fallbacks, expansion pages), so a replay needs nothing else.
2. Review the draft. Identity evidence (names, ABV, ids, production status, `alias_alt`, `beer_ibu`) and paging (`nbHits`, `nbPages`, `page`, `hitsPerPage`) are copied unchanged, never derived from the saved hits. Only rating values are masked, keeping None / zero / positive distinctions. Fields the runtime does not read are dropped; the allowlist is checked against the code by `tests.test_untap_corpus_tools`.
3. `python3 -m tests.corpus_tools finalize NAME --expect status=ok --expect url=... [--excluded-url ...]` replays the draft strictly and writes `NAME.json` only if the replay is clean. Expected values are never inferred.

Recording and finalization both refuse HTTP 429, other non-200 responses, malformed requests/JSON and response-shape issues on every exchange. Shape annotations are reserved for hand-authored cases; they cannot authorize invalid live captures. Finalization revalidates edited drafts, rejects unconsumed response fields, and requires an explicit recognized status plus known expected result fields. Malformed responses retain their status, and a refused capture cannot begin another fetch or navigation. Listeners and transport authority are cleaned up even when the flow fails. Drafts end in `.draft`, so the corpus test never picks them up.

First live use: confirm that the exchange count equals the requests the run made (compare with `--debug` request counts). The recorder assumes the page's `response` event fires for the UI search, while direct fetches are recorded from `evaluate`; the offline tests simulate both, including multi-request UI batches and queryless entries, but only a live run can show how the real page behaves. All search-bearing entries receive the typed query during replay so a query mismatch still fails.

### Real captures (2026-10-13)

- `live_badlands_fazy`: shortened brewery name and four vintage-family hits. The base release is currently in production; this is not a retired-base example.
- `live_bas_canada_sloche`: Bas-Canada menu name versus Brasserie du Bas-Canada.
- `live_guinness_draught`: ten hits across two advertised pages; exact identity correctly skips expansion.

All include the real empty-query search-page bootstrap before the typed query and pass strict replay after sanitization. A separate Guinness/Stout expansion attempt was refused at exchange 11 because `beer_slug` failed the shape canary; no fixture was retained. Actual expansion and retired-base live examples remain to be added. The existing synthetic cases retain that coverage.

The canary requires name, brewery, ABV and bid on every hit. Missing slug, ratings or style are incomplete confirmation metadata, reported with result/hit indexes and bid by the smoke check, rather than schema failures. Present values of the wrong type still fail validation. Missing paging or identity fields still refuse live captures.

### Additional real captures (2026-10-14)

- `live_guinness_stout`: actual expansion across 21 exchanges; missing slug metadata is tolerated, and reaching the page cap retains an ambiguous/incomplete result.
- `live_boston_lager`: current Boston Lager and same-ABV retired Boston Lager (1985–2022). The retired hit has an explicit date suffix; this is real family evidence, not a reproduction of the synthetic retired exact-base guard.
- `live_messorem_collaboration`: A7Y7 X Humble Sea is listed under Messorem (with a trailing space in its brewery name).
- `live_no_match`: intentionally nonexistent menu identity; real zero-hit primary and fallback responses.

Each records the search-page bootstrap and passes sanitized strict replay. No rate-limit probing was performed. The earlier refused expansion attempt remains documented as a historical validation result.
