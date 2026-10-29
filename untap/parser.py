"""Strict TSV menu parsing with optional style and shared matcher text helpers.

Menu rows contain brewery, beer and ABV, optionally followed by style. Explicit
fields are preserved; no menu-layout guessing or style stripping is performed.
"""
import re
import unicodedata
from typing import Iterable, List, Tuple
from untap.types import NormalizedMenuRecord

FORMAT_TABULAR = "tab-separated"
NORMALIZED_RECORD_FIELDS = ("brewery", "beer", "style", "menu_abv", "query", "original")
COLLABORATION_SEPARATOR_RE = re.compile(r"\s+[xX]\s+")
ABV_RE = re.compile(r"(\d+(?:[.,]\d{1,2})?)(?:\s*%\s*(?:abv)?)?", re.IGNORECASE)
SUPPORTED_MENU_FORMATS = """Supported menu format: tab-separated rows
brewery<TAB>beer<TAB>ABV
brewery<TAB>beer<TAB>ABV<TAB>style
Example: Badlands<TAB>Pop Pop (2026)<TAB>6.5%<TAB>IPA
Use three or four fields per row. Brewery, beer and ABV are required; the style
column may be omitted or empty. ABV accepts decimal points or commas, with or
without a percent sign, including zero. Blank lines are ignored.
An optional brewery / beer / ABV header, with optional style, is accepted.
Convert older menu layouts to this format before searching.
"""

class MenuValidationError(ValueError):
    """Invalid menu input; no queries should run."""


def supported_formats_help():
    return SUPPORTED_MENU_FORMATS


def menu_format_display_name(format_name):
    return "Tab-separated rows" if format_name == FORMAT_TABULAR else str(format_name)


def normalize(text):
    text = unicodedata.normalize("NFKD", text)

    text = "".join(
        c for c in text
        if not unicodedata.combining(c)
    )

    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)

    return " ".join(text.split())

def clean_block_text(text):
    return "\n".join(
        line.strip()
        for line in text.splitlines()
        if line.strip()
    )

def final_query_cleanup(line):
    """
    Last cleanup step after other parsing.
    """

    # Remove any percentage that survived
    line = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*%",
        " ",
        line,
    )

    # Remove trailing separator(s), including menu delimiters such as //.
    line = re.sub(
        r"(?:\s*(?:\|+|//+|—|–|-)\s*)+$",
        "",
        line,
    )

    # Remove leading separators
    line = re.sub(
        r"^(?:\s*(?:\|+|//+|—|–|-)\s*)+",
        "",
        line,
    )

    # Collapse menu separators surrounded by whitespace into spaces.
    # This includes a plain ASCII hyphen when it is used structurally, e.g.
    #   Hoof Hearted Brewing - Papa Dodo's
    # while preserving embedded/name hyphens such as "X-Ray".
    line = re.sub(
        r"\s+(?:\||—|–|-)\s+",
        " ",
        line,
    )

    # Clean cases like:
    # Hoof Hearted Brewing - Papa Dodo's -
    line = re.sub(
        r"\s+-\s*$",
        "",
        line,
    )

    line = re.sub(
        r"\s{2,}",
        " ",
        line,
    )

    return line.strip()

def collaboration_brewery_for_search(brewery):
    """Return search-only brewery text with a structural ``A x B`` separator removed."""
    brewery = (brewery or "").strip()
    if not brewery or not COLLABORATION_SEPARATOR_RE.search(brewery):
        return brewery
    return re.sub(COLLABORATION_SEPARATOR_RE, " ", brewery).strip()

def join_brewery_and_beer(brewery, beer):
    brewery = (brewery or "").strip()
    beer = (beer or "").strip()

    if not brewery:
        return beer

    if not beer:
        return brewery

    # Avoid duplication when a single-line entry already contains brewery.
    brewery_norm = normalize(brewery)
    beer_norm = normalize(beer)

    if brewery_norm and f" {brewery_norm} " in f" {beer_norm} ":
        return beer

    search_brewery = collaboration_brewery_for_search(brewery)
    return f"{search_brewery} {beer}".strip()

def validate_normalized_menu(items):
    """Validate the parser-to-matcher record contract.

    This validation is deliberately independent from raw-format validation:
    the first proves that source text follows a supported structure; the
    second proves that the parser produced safe records for the matcher.
    """
    if not items:
        raise MenuValidationError(
            "The menu produced no normalized beer records."
        )

    expected_keys = set(NORMALIZED_RECORD_FIELDS)

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise MenuValidationError(
                f"Normalized record {index} is not a mapping."
            )

        if set(item) != expected_keys:
            raise MenuValidationError(
                f"Normalized record {index} has an invalid field set."
            )

        for field in ("original", "beer", "query"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                raise MenuValidationError(
                    f"Normalized record {index} has an empty {field!r} field."
                )

        if len(normalize(item["beer"])) < 3:
            raise MenuValidationError(
                f"Normalized record {index} has a too-short beer identity."
            )
        if len(normalize(item["query"])) < 3:
            raise MenuValidationError(
                f"Normalized record {index} has a too-short search query."
            )

        for field in ("brewery", "style"):
            value = item.get(field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise MenuValidationError(
                    f"Normalized record {index} has an invalid {field!r} value."
                )

        abv = item.get("menu_abv")
        if abv is not None:
            if isinstance(abv, bool) or not isinstance(abv, (int, float)):
                raise MenuValidationError(
                    f"Normalized record {index} has a non-numeric ABV."
                )
            if not (0.0 <= float(abv) <= 100.0):
                raise MenuValidationError(
                    f"Normalized record {index} has an out-of-range ABV: {abv}."
                )

    return items

def show_parsed_menu(items):
    print()
    print("Generated search queries")
    print("=" * 70)

    for i, item in enumerate(items, start=1):
        print(
            f"{i:>2}. {item['query']}"
        )

        if normalize(item["original"]) != normalize(item["query"]):
            print(
                f"    from: {item['original']}"
            )

    print()

def parse_menu_lines(lines: Iterable[str]) -> List[NormalizedMenuRecord]:
    """Validate and normalize TSV rows in one pass, with source line errors."""
    items: List[NormalizedMenuRecord] = []
    first_row = True
    for line_number, raw in enumerate(lines, start=1):
        text = raw.rstrip("\r\n")
        if line_number == 1:
            text = text.lstrip("\ufeff")
        if not text.strip():
            continue
        fields = [field.strip() for field in text.split("\t")]
        if first_row and [field.casefold() for field in fields] in (
                ["brewery", "beer", "abv"], ["brewery", "beer", "abv", "style"]):
            first_row = False
            continue
        first_row = False
        if len(fields) not in (3, 4):
            raise MenuValidationError(
                f"Line {line_number} has {len(fields)} tab-separated fields; expected 3 or 4: "
                "brewery<TAB>beer<TAB>ABV[<TAB>style]. Style may be omitted or empty. Convert older menu layouts to this format.")
        brewery, beer, abv_text = fields[:3]
        style = fields[3] if len(fields) == 4 else ""
        for name, value in (("brewery", brewery), ("beer", beer)):
            if not value:
                raise MenuValidationError(f"Line {line_number} has an empty {name} field.")
        match = ABV_RE.fullmatch(abv_text)
        if match is None:
            raise MenuValidationError(f"Line {line_number} has invalid ABV {abv_text!r}; expected an ABV such as 6.5, 6,5 or 6.5%.")
        abv = float(match.group(1).replace(",", "."))
        if not 0 <= abv <= 100:
            raise MenuValidationError(f"Line {line_number} has out-of-range ABV {abv}.")
        if len(normalize(beer)) < 3:
            raise MenuValidationError(f"Line {line_number} has a too-short beer identity.")
        items.append({"original": text, "brewery": brewery, "beer": beer,
                      "style": style or None, "menu_abv": abv,
                      "query": join_brewery_and_beer(brewery, beer)})
    if not items:
        raise MenuValidationError("The menu file is empty or contains only a header.")
    return items


def validate_and_parse_menu_lines(lines: Iterable[str]) -> Tuple[str, List[NormalizedMenuRecord]]:
    items = parse_menu_lines(lines)
    validate_normalized_menu(items)
    return FORMAT_TABULAR, items


def read_validated_menu(filename: str) -> Tuple[str, List[NormalizedMenuRecord]]:
    with open(filename, encoding="utf-8-sig") as source:
        return validate_and_parse_menu_lines(source)
