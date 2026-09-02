# Untap v83

Untap v83 builds directly on the validated v82 report-filter baseline. It places confirmed and ambiguous top-level report results in one rating-sorted list while preserving the existing ambiguous-card presentation and match-score candidate ordering. Matching decisions, parser behavior, ABV handling, Algolia transport, CSV/resume, publishing, smoke behavior, pacing, and performance are unchanged.

## Mobile-friendly HTML results

Use `--html` with `--menu` or `--file`:

```bash
python3 untap.py --menu menu10.txt --html
python3 untap.py --menu menu10.txt --html --report-title "September Bottle Share"
```

`--report-title` is optional and requires `--html`. When supplied, the descriptive title appears in both the browser tab and the report heading. If omitted, the title remains `Untap Results`. Empty titles are rejected before browser startup.

Untap still writes its normal `results.csv` and terminal summary. With `--html`, it also writes `results.html`. The report is a single portable file with inline CSS and a small inline JavaScript style filter; it has no external assets or runtime dependencies and can be opened directly from disk in a desktop or mobile browser.

Confirmed and ambiguous results now share one **Results** list sorted from highest report rating to lowest. A confirmed result uses its own Untappd rating. An ambiguous result uses the Untappd rating of its highest match-score candidate; a lower-scoring candidate never changes the result's list position even if that candidate has a higher beer rating. The ambiguous card itself is unchanged, and its candidates remain ordered by match score rather than rating. Results without a usable sort rating appear after rated results. Canonical Untappd beer links remain unchanged.

v80 derives broad style groups only from canonical Untappd `type_name` values actually present in the report. The group is the leading component before Untappd's structural `" - "` subtype separator; a style without that separator remains its own group. No style taxonomy or predefined group list exists in Untap. v82 presents those same case-insensitively sorted, checked-by-default filters as selectable chips with a clear selected checkmark, hover treatment, and keyboard focus state. Unselecting a group immediately hides beer cards in that family; selecting it again restores them. Detailed Untappd styles remain visible on the beer cards.

The report is generated only from already completed `MatchResult` data. It makes no additional Untappd requests and has no parsing, matching, browser, Algolia, or CSV responsibility. v78 also embeds the report title, generation date, total beer count, confirmed count, and needs-review count as simple HTML `<meta>` fields so a later archive publisher can index reports without understanding matcher internals.

## Local report archive publishing

After Untap has generated a v78+ HTML report, publish it into a local `untap-results` repository with:

```bash
python3 untap_publish.py results.html ../untap-results
```

The publisher reads the embedded `untap-*` metadata, validates the report, derives a permanent filename such as:

```text
reports/2026-09-01-pien-new-arrivals-september-2026.html
```

and regenerates the archive `index.html` with reports ordered newest-first. The descriptive report title is the logical archive identity; the embedded report date is generation metadata used when the report is first published. By default the publisher refuses to replace an existing logical report and fails closed if the source report or an already archived HTML report has malformed/missing Untap metadata.

When a report has intentionally been regenerated, replacement must be requested explicitly:

```bash
python3 untap_publish.py results.html ../untap-results --replace
```

`--replace` matches an existing logical report by normalized descriptive title, even when the regenerated report has a later generation date. The existing archive filename is preserved, so replacement keeps the public report URL stable. The source and all existing archived reports still undergo the normal validation first. If replacement succeeds but the subsequent index update fails, the previous report is restored. If no report with that logical title exists, `--replace` behaves like an ordinary new publication. A filename collision belonging to a different title is never replaceable through this flag.

`untap_publish.py` is intentionally local-filesystem-only. It does **not** run Git, authenticate with GitHub, call GitHub APIs, push commits, or make network requests. After a successful local publication it prints the remaining explicit Git commands (`git add .`, a descriptive `git commit`, and `git push`). This keeps credentials and public publication under user control while removing the tedious filename/copy/index work.

## Manual live smoke check

Untap now has a small production integration probe that can be run manually on any machine that already runs Untap:

```bash
python3 untap.py --smoke-test
```

Add `--debug-timing` when transport timing is useful. The smoke check is deliberately tiny and serial. It verifies the live UI bootstrap, Algolia request-template capture, authoritative browser-context transport, the confirmed-result response contract, and known beer identities. It never asserts a fixed rating or ratings count, and it does not deliberately probe Untappd's rate-limit threshold.

The current operating model is **manual/local only**. GitHub automation is not used and no `.github/workflows/` configuration is included. The smoke command is intentionally platform-neutral so it can be invoked manually now and, if desired later, by `launchd`, `cron`, a NAS, a VPS, or another scheduler without changing Untap itself.

Exit status is machine-usable: `0` means healthy; distinct nonzero codes identify bootstrap/template, direct transport, response-contract, identity, HTTP 429, or unexpected runtime failures.


## Self-healing search transport

The first search still uses Untappd's rendered search UI to capture the current Algolia request shape. Later primary and fallback searches remain serial browser-context fetches.

If one of those direct searches fails for a non-429 transport reason, v73 now:

1. invalidates the cached request template;
2. runs that same search once through the established UI path;
3. captures a fresh request template from the UI request;
4. uses the UI result for that item; and
5. resumes direct serial transport for later searches.

Recovery is deliberately bounded to one UI attempt for the affected search. There is no retry loop. HTTP 429 remains fail-fast and never triggers recovery, because rate limiting is not evidence that the request shape is stale and an extra UI request would only add traffic.

With `--debug-timing`, the transport summary reports UI bootstrap searches, UI recovery searches, template invalidations, successful/failed recoveries, direct searches, errors, and 429s. A healthy menu9 regression should normally show zero recoveries.

## Full mypy coverage

Local static validation runs mypy across all eight runtime modules:

```bash
python3 -m mypy untap_types.py untap_parser.py untap_matcher.py untap_batch.py untap_untappd.py untap_smoke.py untap_report.py untap_publish.py untap.py
```

`untap_types.py` now includes explicit request/event/result contracts for the Algolia transport boundary. The live request-template mutation and browser-fetch response path are annotated so payload-shape wiring is no longer outside static checking.

## Safety properties preserved

- Matching/scoring/ambiguity logic is unchanged.
- Fallback-query selection and expansion behavior are unchanged.
- Confirmed-result Algolia authority from v70 is unchanged.
- Search transport remains fully serial; no parallelism was added.
- No sleeps, pacing, or automatic backoff were added.
- HTTP 429 remains fail-fast.
- One non-429 direct failure can no longer poison the remaining batch through a stale cached template.
- Invalid/validation-only menus still fail before browser startup.

## Validation

Run:

```bash
python3 -m mypy untap_types.py untap_parser.py untap_matcher.py untap_batch.py untap_untappd.py untap_smoke.py untap_report.py untap_publish.py untap.py
python3 -m unittest discover -v
python3 untap.py --help
python3 untap.py --menu menu9.txt --debug-timing
```

The deterministic v83 suite contains 137 tests in this release artifact. The live acceptance target remains the historical menu9 result: 38 confirmed beers, one deliberate Populus ambiguity, zero unnecessary detail-page fallbacks, and normally zero transport recoveries.
