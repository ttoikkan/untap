# Supported menu input

`--menu` accepts tab-separated rows with three required columns, **brewery, beer, ABV**, and an optional fourth **style** column.

```text
brewery<TAB>beer<TAB>ABV<TAB>style
Badlands<TAB>Pop Pop (2026)<TAB>6.5%<TAB>IPA
All My Friends<TAB>Metal<TAB>7,0
```

`<TAB>` means an actual tab character. An optional three- or four-column header with those column names is accepted. Rows with and without style may be mixed. Blank lines and a leading UTF-8 BOM are ignored. Brewery, beer and ABV are required. Style may be omitted entirely or left empty. ABV must be between 0 and 100, with up to two decimal places; decimal commas, an optional percent sign and zero are supported. Beer-name punctuation, accents and original row delimiters are preserved.

Legacy brewery-heading blocks, multiline beer/style/ABV records, `//` records, webshop catalogs and copied tap lists are no longer parsed. Convert them to TSV before searching. Invalid input reports its source line before any browser or network activity.

```bash
untap run --formats
untap run --validate-menu menu.tsv --show-queries
untap run --menu menu.tsv --report-title "My menu"
```

Single-beer queries and `--file` one-query-per-line input remain separate search modes. Batch runs save HTML and JSON automatically; add the boolean `--csv` flag for spreadsheet export.
