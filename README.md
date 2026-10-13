# Untap

Untap matches beer menus against Untappd and creates self-contained HTML reports. Review uncertain matches locally, save your choices, and publish completed reports to a local archive.

## Install

Python 3.9 or newer is required. Install with pipx, then download the browser used for searches:

```bash
pipx install git+https://github.com/ttoikkan/untap.git
untap-install-browser
untap --version
```

From a checkout, install with `pipx install .`; update your installed copy after local changes with `pipx install --force .`. If the installed commands are missing from your shell, run `python3 -m pipx ensurepath` and open a new terminal.

Browser installation is explicit. Help, menu validation and offline report operations work without Chromium. Searches explain how to install it if it is missing.

## Process a menu

```bash
untap run --validate-menu menu.tsv
untap run --menu menu.tsv --report-title "My menu"
```

The input is a tab-separated file with four columns: **brewery, beer, ABV, style**. Style may be empty, but its column must remain. An optional header, blank lines and a UTF-8 BOM are supported. ABV accepts decimal points or commas and an optional percent sign, including zero.

```text
brewery	beer	abv	style
Badlands	Green Fields	6.5%	IPA
```

See [SUPPORTED_MENU_FORMATS.md](SUPPORTED_MENU_FORMATS.md) for the exact input contract. Older free-form menu formats are no longer supported.

Each batch run creates a folder under `results/` in the current directory. It contains `results.html` and `results.json`; `--csv` also writes `results.csv` in that folder. `--csv` takes no filename. Text cells beginning with `=`, `+`, `-`, `@`, a tab or a carriage return receive a leading apostrophe to prevent spreadsheet formula interpretation. This also affects legitimate names beginning with those characters; numeric cells and JSON/HTML data are unchanged. Add `--debug` to retain diagnostic output.

For a single beer, results are printed in the terminal without creating a report folder:

```bash
untap run "Badlands Green Fields"
```

Use `untap --help` for the command list and `untap run --help` for search options. Unknown options fail before searching.

## Preview and review

Open `results.html` directly in your browser for a static preview. For local review with saving and candidate retrieval:

```bash
untap review results/<run-folder>/
```

The review server runs on the local machine and opens the report in your browser. Confirm candidates, change a selection, or add a candidate by its Untappd beer URL. Candidate retrieval sends an explicit request to Untappd. Saving creates a new reviewed run folder and preserves the original snapshot and decision history. Stop the server with Ctrl-C.

Candidates excluded because their brewery or ABV conflicts with the menu appear as inspection links with their exclusion reasons. These links are separate from selectable candidates and cannot be confirmed directly. A failed match remains unresolved.

Static reports can also store choices in the browser and export them. Apply that export to its matching snapshot:

```bash
untap refresh results/<run-folder>/ --selections selections.json
```

Browser choices are never applied automatically. Pending candidate URLs in an export require `--fetch-candidates`, which contacts Untappd. If an old export no longer matches, refresh the original snapshot and export choices from its new HTML.

## Continue an unfinished run

After an HTTP 429, wait for the rate limit to clear, then use:

```bash
untap run --continue results/<unfinished-run-folder>/
```

Continuation searches only rate-limited and not-attempted rows. Completed matches, failed searches, ambiguous results, manual decisions and item IDs are retained. It creates a sibling folder and leaves the original run untouched. A normal menu run searches the entire menu again.

During a batch, Untap writes a full `results.input.json` manifest and flushes each completed row to `results.partial.jsonl`. Ctrl-C and ordinary exceptions also save a final snapshot and report with unfinished rows marked **Not Attempted**. Recovery files remain after incomplete runs or failed saves and are removed after all outputs save successfully.

Continuation uses `results.json` when available, otherwise the manifest and journal. A torn final journal record is ignored with a warning; malformed complete records and mismatched identities are rejected. For a crashed legacy v103 run without a manifest, provide the exact original menu in its original order:

```bash
untap run --continue results/<legacy-run-folder>/ --recovery-menu original-menu.tsv
```

Older snapshots that silently omitted rows cannot recover the missing identities; process the original menu again. Incomplete reports cannot be published or registered for refresh.

## Publish a report

```bash
untap publish results/<reviewed-run-folder>/ ../untap-results
```

Publishing copies a completed report into a local archive and updates its index. Use `--replace` to replace an existing archive entry. This does not commit or push the archive to Git. Keep your saved run snapshots for future review and refresh.

## Refresh saved reports

```bash
untap refresh results/<run-folder>/
untap refresh results/<run-folder>/ --output results/my-refreshed-report
```

Refresh rebuilds HTML from the saved snapshot without repeating the menu search. It creates a new output folder and retains applied manual decisions. Use `--csv` for optional CSV output. To publish the refreshed report as well, add `--archive ../untap-results --replace`.

For several reports, create a configuration whose paths are relative to the configuration file:

```json
{
  "reports": [
    {
      "source": "results/my-reviewed-run",
      "archive": "../untap-results",
      "replace": true
    }
  ]
}
```

```bash
untap refresh --batch refresh-reports.json
```

Use reviewed snapshots as sources to preserve your choices. Entries may include a `selections` path. Omit `archive` and `replace` for refresh-only operation. Malformed configuration is rejected before starting; individual failures are reported while remaining entries continue, with exit code 2 if any fail. Successful entries are retained.

Register a completed menu run with its required report title:

```bash
untap run --menu menu.tsv --report-title "My menu" \
  --register-refresh refresh-reports.json
```

Registration skips an existing logical menu title and keeps its current entry unchanged. Missing sources are skipped with a warning; other invalid entries still require correction. The configuration is not automatically changed to point to refreshed outputs.

## Inspect search results

```bash
untap inspect --query "Kin Kinetic Hazy"
untap inspect --menu menu.tsv
```

Inspection saves raw search hits under `inspections/` in the current directory, without making matching decisions. Use `untap inspect --help` for query files, paging and diagnostics.

`--shadow-search-transport N` on a search compares up to N successful browser captures with diagnostic replay requests. It sends additional requests only when explicitly enabled. Replay candidates never affect matching, and HTTP 429 stops further traffic.

## Use a source checkout

Unified commands also work without installation:

```bash
python3 -m untap.cli --help
python3 -m untap.cli run --menu menu.tsv
```

`python3 -m untap` runs the same unified CLI from a checkout or installation. Runtime code lives in the `untap/` package. Legacy query forms, `python3 untap.py`, and the separate `untap-review`, `untap-refresh`, `untap-publish` and `untap-inspect` commands remain supported. Leading subcommand names are reserved: for a query beginning with one, use `untap run "review Brewery Beer"` or `untap -- "review Brewery Beer"`.

## Develop and validate

```bash
python3 -m pip install -r requirements-dev.txt
python3 -B -m unittest discover -s tests -t .
python3 -m mypy untap untap_*.py
```

The ordinary suite includes strict Playwright-level search replay, package/compatibility checks, frozen decision/output cases, and 2,000 seeded invariant cases. Run a larger invariant sample with:

```bash
UNTAP_INVARIANT_SEED=108 UNTAP_INVARIANT_CASES=10000 python3 -B -m unittest tests.test_untap_decision_invariants
```

Installed-wheel checks are optional in source-only runs. To exercise entry points, bundled assets, missing-browser diagnostics and output equivalence outside the checkout:

```bash
python3 -m pip install build
untap_check_dir=$(mktemp -d)
python3 -m build --wheel --outdir "$untap_check_dir/dist"
python3 -m venv "$untap_check_dir/venv"
"$untap_check_dir/venv/bin/python" -m pip install "$untap_check_dir"/dist/untap-*.whl
UNTAP_TEST_ENV="$untap_check_dir/venv" python3 -B -m unittest discover -s tests -t .
```

Run `untap smoke` only when you want the explicit live integration check. It contacts Untappd.

See [ARCHITECTURE.md](ARCHITECTURE.md) for dependencies and decision rules, and [CHANGELOG.md](CHANGELOG.md) for release history. The six per-module changelogs are retained as historical references. Distribution and CLI versions come from `untap/version.py`. Replay fixtures and their contribution rules are documented in [the corpus guide](tests/testdata/search_corpus/README.md).
