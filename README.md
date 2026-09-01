# Untap v78

Untap v78 builds directly on the validated v77 HTML-report baseline. It adds optional human-readable report identity through `--report-title` plus machine-readable report metadata for future archive publishing. Parsing, matching, ambiguity policy, ABV handling, Algolia transport, self-healing, rate-limit behavior, CSV/resume, smoke behavior, pacing, and performance are unchanged.

## Mobile-friendly HTML results

Use `--html` with `--menu` or `--file`:

```bash
python3 untap.py --menu menu10.txt --html
python3 untap.py --menu menu10.txt --html --report-title "September Bottle Share"
```

`--report-title` is optional and requires `--html`. When supplied, the descriptive title appears in both the browser tab and the report heading. If omitted, the title remains `Untap Results`. Empty titles are rejected before browser startup.

Untap still writes its normal `results.csv` and terminal summary. With `--html`, it also writes `results.html`. The report is a single portable file with inline CSS and no JavaScript or external assets, so it can be opened directly in a desktop or mobile browser.

Confirmed beers are sorted from highest Untappd rating to lowest. Every confirmed beer name links to its canonical Untappd beer page. The **Needs review** section keeps each uncertain result grouped separately; ambiguity candidates are sorted by match score, not beer rating, and each available candidate beer name links to its own canonical Untappd page.

The report is generated only from already completed `MatchResult` data. It makes no additional Untappd requests and has no parsing, matching, browser, Algolia, or CSV responsibility. v78 also embeds the report title, generation date, total beer count, confirmed count, and needs-review count as simple HTML `<meta>` fields so a later archive publisher can index reports without understanding matcher internals.

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
python3 -m mypy untap_types.py untap_parser.py untap_matcher.py untap_batch.py untap_untappd.py untap_smoke.py untap_report.py untap.py
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
python3 -m mypy untap_types.py untap_parser.py untap_matcher.py untap_batch.py untap_untappd.py untap_smoke.py untap_report.py untap.py
python3 -m unittest discover -v
python3 untap.py --help
python3 untap.py --menu menu9.txt --debug-timing
```

The deterministic v78 suite contains 106 tests in this release artifact. The live acceptance target remains the historical menu9 result: 38 confirmed beers, one deliberate Populus ambiguity, zero unnecessary detail-page fallbacks, and normally zero transport recoveries.
