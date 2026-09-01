# Supported raw menu formats

Untap deliberately supports a small set of recognizable menu structures. For ambiguous or inconsistent source menus, normalize the input to the tab-separated format before running Untappd queries.

## 1. Tab-separated rows — recommended

```text
brewery<TAB>beer<TAB>ABV<TAB>style
Badlands<TAB>Pop Pop (2026)<TAB>6.5%<TAB>IPA
```

This is the preferred canonical raw-input format because the columns explicitly define identity and metadata.

## 2. Beer / Style + ABV / Brewery

```text
Pop Pop (2026)
IPA | 6.5%
Badlands
```

## 3. Beer // ABV // Style

```text
Heineken // 0% // Non-Alcoholic
```

## 4. Supported webshop/catalog layout

The parser supports the catalog structure already covered by its regression corpus, including repeated product-title lines and price rows.

```text
Bad Bones - EKG Double New England IPA
Regular price€15,50 EUR
```

## 5. Brewery-heading blocks

```text
CLOUDWATER
Fuzzy — 4.2% ABV
Chubbles — 10%

VERDANT
Putty — 8%
Lightbulb — 4.5%
```

A brewery heading scopes the following `Beer — ABV` rows until the next brewery heading. Style may be unknown.

## 6. Beer/style + ABV/IBU/brewery pairs

```text
A Moment of Now IPA - New England / Hazy
7.3% ABV • N/A IBU • Factory Brewing
```

Records occur in two-line pairs. The second line must carry an ABV and brewery; IBU is accepted as source metadata but is not required by the matcher.

## 7. Tap-list blocks

```text
Tipping Point IPA - Imperial / Double New England / Hazy
8% ABV • N/A IBU • Factory Brewing •
(4.2)
0,2L7.00 EUR
0,3L10.00 EUR
0,4L12.00 EUR
```

The beer/style and ABV/IBU/brewery lines define identity. Standalone displayed ratings and serving-size/price rows are ignored as source-site presentation metadata.

## Contract

These seven structures are the deliberately supported formats, not a promise that arbitrary menu text will be interpreted correctly. A later validation stage will enforce this contract before any Untappd network activity. 
## v56 validation behavior

Starting with v56, `--menu` input is validated before Playwright is imported or
Chromium is started. A strongly recognized but malformed supported format fails
closed; Untap does not silently reinterpret it with another parser.

Use:

```bash
python3 untap.py --formats
python3 untap.py --validate-menu menu.txt
python3 untap.py --validate-menu menu.txt --show-queries
```

`--validate-menu` is local-only. It performs raw-format detection, structural
validation, parsing, and normalized-record validation, then exits without
contacting Untappd.

If a source menu is ambiguous or unsupported, convert it to the recommended
four-column tab-separated format before querying.
