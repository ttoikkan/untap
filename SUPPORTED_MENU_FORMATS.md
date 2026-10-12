# Supported menu input (v102+)

`--menu` accepts one format: exactly four tab-separated columns, **brewery, beer, ABV, style**.

```text
brewery<TAB>beer<TAB>ABV<TAB>style
Badlands<TAB>Pop Pop (2026)<TAB>6.5%<TAB>IPA
```

`<TAB>` means an actual tab character. An optional header with those column names is accepted. Blank lines and a leading UTF-8 BOM are ignored. Brewery, beer and ABV are required. Style may be empty; retain the fourth column's tab. ABV must be a percentage between 0 and 100, with up to two decimal places; decimal commas and zero are supported. Beer-name punctuation, accents and original row delimiters are preserved.

Legacy brewery-heading blocks, multiline beer/style/ABV records, `//` records, webshop catalogs and copied tap lists are no longer parsed. Convert them to TSV before searching. Invalid input reports its source line before any browser or network activity.

```bash
untap run --formats
untap run --validate-menu menu.tsv --show-queries
untap run --menu menu.tsv --report-title "My menu"
```

Single-beer queries and `--file` one-query-per-line input remain separate search modes. Batch runs save HTML and JSON automatically; add the boolean `--csv` flag for spreadsheet export.
