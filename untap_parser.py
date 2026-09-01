"""Menu parsing for untap.

Extracted from untap_stateful_v52 without intended behavior changes.
The parser normalizes menu text into records consumed by the Untappd matcher.
It deliberately has no Playwright, Algolia, HTTP, or Untappd-page dependencies.
"""

import re
import unicodedata
from typing import Iterable, List, Tuple, cast

from untap_types import NormalizedMenuRecord

SUPPORTED_MENU_FORMATS = """Supported raw menu formats
==========================

1. Tab-separated rows (recommended)
   brewery<TAB>beer<TAB>ABV<TAB>style

   Example:
   Badlands<TAB>Pop Pop (2026)<TAB>6.5%<TAB>IPA

2. Beer / Style + ABV / Brewery records
   Beer name
   Style | ABV
   Brewery

   Example:
   Pop Pop (2026)
   IPA | 6.5%
   Badlands

3. Beer // ABV // Style records
   Beer name // ABV // Style

   Example:
   Heineken // 0% // Non-Alcoholic

4. Supported webshop/catalog rows
   Product lines in the catalog layout already recognized by Untap, including
   duplicate product-title lines and price rows such as "Regular price...".

   Example:
   Bad Bones - EKG Double New England IPA
   Regular price€15,50 EUR

5. Brewery-heading blocks
   BREWERY HEADING
   Beer — ABV
   Beer — ABV

   Example:
   CLOUDWATER
   Fuzzy — 4.2% ABV
   Chubbles — 10%

6. Beer/style + ABV/IBU/brewery pairs
   Beer name + style
   ABV • IBU • Brewery

   Example:
   A Moment of Now IPA - New England / Hazy
   7.3% ABV • N/A IBU • Factory Brewing

7. Tap-list blocks
   Beer name + style
   ABV • IBU • Brewery
   (displayed rating)
   serving-size/price rows

   Example:
   Tipping Point IPA - Imperial / Double New England / Hazy
   8% ABV • N/A IBU • Factory Brewing •
   (4.2)
   0,2L7.00 EUR

For ambiguous, inconsistent, or unsupported source menus, convert the data to
format 1 before running Untappd queries. The tab-separated format is the
preferred canonical raw-input format.
"""


def supported_formats_help():
    """Return the canonical user-facing description of supported menu formats."""
    return SUPPORTED_MENU_FORMATS


def print_supported_formats():
    """Print the canonical user-facing description of supported menu formats."""
    print(SUPPORTED_MENU_FORMATS)

STYLE_WORDS = {
    "ipa",
    "dipa",
    "tipa",
    "neipa",
    "apa",
    "lager",
    "pilsner",
    "pils",
    "stout",
    "porter",
    "sour",
    "gose",
    "ale",
    "barleywine",
    "lambic",
    "farmhouse",
    "saison",
    "kolsch",
    "kölsch",
    "witbier",
    "wheat",
    "helles",
    "bock",
    "dubbel",
    "tripel",
    "quadrupel",
    "quad",
    "radler",
    "cider",
}

NOISE_WORDS = {
    "abv",
    "ibu",
    "alc",
    "vol",
    "draft",
    "draught",
    "tap",
    "can",
    "bottle",
    "bottled",
    "cl",
    "ml",
    "oz",
    "pint",
    "half",
    "glass",
}

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

def looks_like_external_rating(line):
    """
    Ignore standalone menu/site ratings that are not Untappd ratings, e.g.:
      (4.5)
      (4.05)
      (3,9)
    """
    return bool(
        re.fullmatch(
            r"\(\s*\d(?:[.,]\d{1,3})?\s*\)",
            line.strip(),
        )
    )

def looks_like_price_line(line):
    """
    Ignore serving-size/price rows such as:
      0,2L7.00 EUR
      0,3L10.00 EUR
      0,4L12.00 EUR
      0.2 L 7.00 EUR
      33cl 8.50 €
    """
    stripped = line.strip()

    return bool(
        re.fullmatch(
            r"\d+(?:[.,]\d+)?\s*(?:l|ml|cl|dl)\s*"
            r"\d+(?:[.,]\d+)?\s*(?:eur|€|\$|£)",
            stripped,
            flags=re.IGNORECASE,
        )
    )

def looks_like_menu_noise_line(line):
    return (
        looks_like_external_rating(line)
        or looks_like_price_line(line)
    )

def remove_menu_noise(text):
    """
    Remove common menu metadata such as:
      - prices
      - ABV / percentages
      - IBU
      - serving sizes
      - trailing separators
    """

    # Prices: €9.90, $8, £6.50
    text = re.sub(
        r"(?:€|\$|£)\s*\d+(?:[.,]\d+)?",
        " ",
        text,
    )

    # Prices: 9.90 €, 8 $, 6.50 £
    text = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:€|\$|£)\b",
        " ",
        text,
    )

    # Percentages / ABV:
    # 6.5%
    # 6.5% ABV
    # 6,5 %
    text = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*%\s*(?:abv)?\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    # Alternative ABV forms:
    # ABV 6.5%
    # ABV: 6.5%
    text = re.sub(
        r"\babv\s*:?\s*\d+(?:[.,]\d+)?\s*%",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    # IBU:
    # 45 IBU
    text = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*ibu\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    # IBU 45 / IBU: 45
    text = re.sub(
        r"\bibu\s*:?\s*\d+(?:[.,]\d+)?\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    # Serving sizes:
    # 440 ml, 33cl, 16 oz
    text = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl|oz)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    # Standalone price-looking number at end
    text = re.sub(
        r"\s+\d{1,2}(?:[.,]\d{1,2})?\s*$",
        "",
        text,
    )

    # Remove dangling separators at end
    text = re.sub(
        r"\s*(?:\||—|–|-)\s*$",
        "",
        text,
    )

    # Collapse spaces
    text = re.sub(
        r"\s{2,}",
        " ",
        text,
    )

    return text.strip()

def looks_like_heading(line):
    """
    Ignore menu headings such as:
      IPA
      DRAFT BEERS
      LAGERS
      GUEST TAPS
    """

    stripped = line.strip()

    if not stripped:
        return True

    lowered = normalize(stripped)

    heading_terms = {
        "beer",
        "beers",
        "draft",
        "draft beers",
        "draught",
        "draught beers",
        "guest taps",
        "guest beers",
        "ipa",
        "ipas",
        "lager",
        "lagers",
        "stout",
        "stouts",
        "sours",
        "sour",
        "cider",
        "ciders",
        "bottles",
        "cans",
        "on tap",
        "tap list",
    }

    if lowered in heading_terms:
        return True

    letters = re.sub(r"[^A-Za-z]", "", stripped)

    if (
        letters
        and stripped.upper() == stripped
        and len(stripped) < 40
        and not re.search(r"\d", stripped)
    ):
        return True

    return False

def strip_bullet(line):
    return re.sub(
        r"^\s*(?:[-*•·▪◦]+\s*|\d+[.)]\s+)",
        "",
        line,
    ).strip()

def remove_style_suffix(text):
    """
    Remove style/metadata fields when separators make them obvious.

    Example:
      Badlands — Fazy (2026) — IPA - American — 6.5%

    becomes approximately:
      Badlands Fazy (2026)
    """

    parts = re.split(
        r"\s*(?:\||\t|—|–)\s*",
        text,
    )

    kept = []

    for part in parts:
        p = part.strip()

        if not p:
            continue

        p_norm = normalize(p)

        # Metadata fields
        if re.search(
            r"\b\d+(?:\.\d+)?\s*(?:abv|ibu|ml|cl|oz)\b",
            p_norm,
        ):
            continue

        # Bare percentage
        if re.fullmatch(
            r"\d+(?:[.,]\d+)?\s*%",
            p,
        ):
            continue

        words = set(p_norm.split())

        if words and words.issubset(
            STYLE_WORDS
            | NOISE_WORDS
            | {
                "american",
                "new",
                "england",
                "imperial",
                "double",
                "triple",
            }
        ):
            continue

        style_phrases = [
            "ipa american",
            "ipa new england",
            "ipa imperial",
            "pale ale",
            "imperial stout",
            "american lager",
            "pilsner german",
            "sour fruited",
            "new england ipa",
        ]

        if any(
            marker in p_norm
            for marker in style_phrases
        ):
            continue

        kept.append(p)

    return " ".join(kept)

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

def menu_line_to_query(line):
    """
    Turn one menu line into an Untappd-friendly search query.
    """

    line = strip_bullet(line)

    if not line or looks_like_heading(line):
        return None

    original = line

    line = remove_menu_noise(line)
    line = remove_style_suffix(line)

    # Remove bracketed menu-only descriptors.
    # Keep years such as (2026).
    line = re.sub(
        r"\((?!\d{4}\))"
        r"(?:draft|draught|tap|can|bottle|guest|new)"
        r"[^)]*\)",
        " ",
        line,
        flags=re.IGNORECASE,
    )

    # Normalize strong separators
    line = re.sub(
        r"\s*(?:\||—|–)\s*",
        " ",
        line,
    )

    # Remove obvious trailing style words
    words = line.split()

    while words:
        last = normalize(words[-1])

        if last in STYLE_WORDS or last in NOISE_WORDS:
            words.pop()
        else:
            break

    line = " ".join(words)

    # Final cleanup
    line = final_query_cleanup(line)

    if len(normalize(line)) < 3:
        return None

    return {
        "original": original,
        "query": line,
    }

def is_metadata_only(line):
    """
    Return True for lines that contain serving/menu metadata but no useful
    beer identity, for example:
      6.5% ABV · 440 ml · €8
      45 IBU
      0.4 l / 9.50 €
    """

    text = strip_bullet(line).strip()

    if not text:
        return True

    cleaned = remove_menu_noise(text)
    cleaned = final_query_cleanup(cleaned)

    # If the normal noise removal leaves nothing meaningful, this is metadata.
    if len(normalize(cleaned)) < 2:
        return True

    norm = normalize(text)
    words = set(norm.split())

    if words and words.issubset(NOISE_WORDS):
        return True

    # Numeric/menu-symbol dominated lines are metadata even when punctuation
    # survives the generic cleanup.
    letters = re.sub(r"[^A-Za-z]", "", text)
    digits = re.sub(r"[^0-9]", "", text)

    if digits and len(letters) <= 3:
        if re.search(
            r"(?:%|abv|ibu|ml|cl|oz|€|\$|£|\b(?:l|dl)\b)",
            text,
            re.IGNORECASE,
        ):
            return True

    return False

def is_style_heading(line):
    """
    Detect section/style headings without treating them as breweries.
    """

    norm = normalize(strip_bullet(line))

    if not norm:
        return False

    section_terms = {
        "beer",
        "beers",
        "draft",
        "draft beer",
        "draft beers",
        "draught",
        "draught beer",
        "draught beers",
        "guest taps",
        "guest beers",
        "on tap",
        "tap list",
        "bottles",
        "cans",
        "bottle",
        "can",
        "ipa",
        "ipas",
        "dipa",
        "tipa",
        "neipa",
        "apa",
        "lager",
        "lagers",
        "pilsner",
        "pilsners",
        "pils",
        "stout",
        "stouts",
        "porter",
        "porters",
        "sour",
        "sours",
        "gose",
        "ale",
        "ales",
        "barleywine",
        "lambic",
        "farmhouse",
        "saison",
        "kolsch",
        "witbier",
        "wheat",
        "helles",
        "bock",
        "dubbel",
        "tripel",
        "quadrupel",
        "quad",
        "radler",
        "cider",
        "ciders",
    }

    return norm in section_terms

def looks_like_brewery_heading(line):
    """
    Conservative brewery-heading heuristic.

    Strong signals are brewery-related words. A short all-caps line is also
    accepted as a possible brewery heading, but only the stateful parser uses
    it and can revise that interpretation based on following lines.
    """

    text = strip_bullet(line).strip()

    if not text or is_metadata_only(text) or is_style_heading(text):
        return False

    norm = normalize(text)

    brewery_markers = {
        "brewery",
        "brewing",
        "brew co",
        "brewing co",
        "beer co",
        "brasserie",
        "brouwerij",
        "bryggeri",
        "panimo",
        "cerveceria",
        "cervejaria",
    }

    if any(marker in norm for marker in brewery_markers):
        return True

    # Obvious menu data generally indicates a beer line, not a brewery line.
    if re.search(
        r"(?:\d+(?:[.,]\d+)?\s*%|\bibu\b|\b\d+\s*(?:ml|cl|oz)\b|€|\$|£)",
        text,
        re.IGNORECASE,
    ):
        return False

    letters = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", text)

    if (
        letters
        and text.upper() == text
        and 1 <= len(norm.split()) <= 6
        and len(text) <= 55
    ):
        return True

    return False

COLLABORATION_SEPARATOR_RE = re.compile(r"\s+[xX]\s+")

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

    if brewery_norm and brewery_norm in beer_norm:
        return beer

    search_brewery = collaboration_brewery_for_search(brewery)
    return f"{search_brewery} {beer}".strip()

def extract_menu_abv(text):
    """Return a numeric ABV hint from menu text, or None."""
    match = re.search(
        r"\b(\d+(?:[.,]\d+)?)\s*%",
        text,
        re.IGNORECASE,
    )

    if not match:
        return None

    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None

STYLE_DETAIL_WORDS = {
    "ipa", "dipa", "tipa", "neipa", "apa", "lager", "pilsner", "pils",
    "stout", "porter", "sour", "gose", "ale", "barleywine", "lambic",
    "farmhouse", "saison", "kolsch", "witbier", "wheat", "helles",
    "bock", "dubbel", "tripel", "quadrupel", "quad", "radler", "cider",
    "american", "new", "england", "hazy", "imperial", "double", "triple",
    "pale", "fruited", "german", "belgian", "session", "west", "coast",
}

def split_inline_style(text):
    """
    Split an inline beer-name + style tail when the tail is clearly style-only.

    Examples:
      A Moment of Now IPA - New England / Hazy
        -> (A Moment of Now, IPA - New England / Hazy)
      Barrel Aged Vanilla Blend Stout - Imperial / Double
        -> (Barrel Aged Vanilla Blend, Stout - Imperial / Double)
    """
    words = list(re.finditer(r"\b[A-Za-zÀ-ÖØ-öø-ÿ]+\b", text))

    for match in words:
        token = normalize(match.group(0))
        if token not in STYLE_WORDS:
            continue

        prefix = text[:match.start()].strip(" \t|-—–/")
        suffix = text[match.start():].strip()
        suffix_words = set(normalize(suffix).split())

        if (
            prefix
            and suffix_words
            and suffix_words.issubset(STYLE_DETAIL_WORDS)
        ):
            return prefix, suffix

    return text, None

def parse_metadata_context(line):
    """
    Parse a metadata line that may also carry a brewery, e.g.:
      7.3% ABV • N/A IBU • Factory Brewing

    Returns a dict with ABV/brewery when the line is metadata-led, otherwise
    None so normal beer-line parsing can continue.
    """
    text = line.strip()
    abv = extract_menu_abv(text)

    # This helper is for metadata-led continuation rows, not normal beer rows
    # that merely contain an inline ABV later in the line.
    metadata_signal = bool(re.match(
        r"^\s*(?:\d+(?:[.,]\d+)?\s*%\s*(?:abv)?|(?:n/?a|\d+(?:[.,]\d+)?)\s+ibu\b|\d+(?:[.,]\d+)?\s*(?:ml|cl|oz)\b|€|\$|£)",
        text,
        re.IGNORECASE,
    ))

    if not metadata_signal:
        return None

    brewery = None
    parts = re.split(r"\s*(?:•|·|▪|◦|\||\t)\s*", text)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if re.search(r"\d+(?:[.,]\d+)?\s*%", part):
            continue
        if re.search(r"\b(?:n/?a\s+)?ibu\b", part, re.IGNORECASE):
            continue
        if re.search(r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl|oz)\b", part, re.IGNORECASE):
            continue
        if re.search(r"€|\$|£", part):
            continue

        if looks_like_brewery_heading(part):
            brewery = final_query_cleanup(part)
            break

    return {
        "abv": abv,
        "brewery": brewery,
    }

def parse_double_slash_beer_metadata(text):
    """Parse the narrow human-menu form ``Beer // ABV // Style``.

    The middle field must be exactly an ABV percentage. This keeps the adapter
    structural rather than style- or brewery-specific and, importantly, treats
    0% as the valid numeric value 0.0 rather than as missing metadata.
    """
    parts = [part.strip() for part in str(text).split("//")]
    if len(parts) != 3 or not parts[0]:
        return None

    abv_match = re.fullmatch(
        r"(\d+(?:[.,]\d+)?)\s*%\s*(?:abv)?",
        parts[1],
        re.IGNORECASE,
    )
    if not abv_match:
        return None

    try:
        abv = float(abv_match.group(1).replace(",", "."))
    except ValueError:
        return None

    return {
        "beer": parts[0],
        "abv": abv,
        "style": parts[2] or None,
    }

def structured_menu_item(
    original,
    beer,
    brewery=None,
    style=None,
    menu_abv=None,
):
    # v40: recognize the already-observed ``Beer // ABV // Style`` structure
    # before generic style/noise cleanup. Generic cleanup can remove ``0%``
    # while leaving the separators behind because 0.0 is a legitimate value.
    slash_metadata = parse_double_slash_beer_metadata(beer)
    if slash_metadata:
        beer = slash_metadata["beer"]
        if menu_abv is None:
            menu_abv = slash_metadata["abv"]
        if not style and slash_metadata.get("style"):
            style = slash_metadata["style"]

    beer = remove_menu_noise(beer)
    # Detect an inline style tail before the older separator-based style
    # remover gets a chance to discard the whole line.
    beer, inline_style = split_inline_style(beer)
    if inline_style and not style:
        style = inline_style
    beer = remove_style_suffix(beer)
    beer = final_query_cleanup(beer)

    if len(normalize(beer)) < 3:
        return None

    query = join_brewery_and_beer(brewery, beer)

    return {
        "original": original.strip(),
        "brewery": (brewery or "").strip() or None,
        "beer": beer,
        "style": (style or "").strip() or None,
        "menu_abv": (
            menu_abv
            if menu_abv is not None
            else extract_menu_abv(original)
        ),
        "query": query,
    }

def collapse_exact_doubled_line(text):
    """
    Collapse copy/paste artifacts where the entire visible text was duplicated
    back-to-back with no separator. The two halves must be exactly identical.
    """
    text = text.strip()

    if len(text) < 6 or len(text) % 2:
        return text

    midpoint = len(text) // 2
    first = text[:midpoint]
    second = text[midpoint:]

    if first == second and len(first.strip()) >= 3:
        return first.strip()

    return text

def parse_trailing_style_abv(line):
    """
    Parse a style/ABV continuation row used by:
        Beer
        Style | 6.5%
        Brewery

    The caller also requires the following non-empty line to look like a
    brewery, keeping the heuristic conservative.
    """
    text = line.strip()

    if not re.search(r"\s(?:\||•|·|—|–)\s", text):
        return None

    abv = extract_menu_abv(text)
    if abv is None:
        return None

    parts = re.split(r"\s*(?:\||•|·|—|–)\s*", text, maxsplit=1)
    if len(parts) != 2:
        return None

    style = final_query_cleanup(parts[0])

    if not style or not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", style):
        return None

    if re.search(
        r"(?:€|\$|£|\b\d+(?:[.,]\d+)?\s*(?:ml|cl|oz|l|dl)\b)",
        style,
        re.IGNORECASE,
    ):
        return None

    return {
        "style": style,
        "abv": abv,
    }

CATALOG_PRICE_RE = re.compile(
    r"^\s*(?:regular\s+price|sale\s+price)\b",
    re.IGNORECASE,
)

CATALOG_STYLE_RE = re.compile(
    r"""
    \s+
    (?P<style>
        Double\s+New\s+England\s+IPA
        (?:\s+Double\s+New\s+Zealand\s+IPA)?
    )
    (?:
        \s*-\s*
        (?P<alias>.+?)
    )?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

def is_catalog_price_line(text):
    """
    Detect website price rows such as:
        Regular price€15,50 EUR
    """
    return bool(CATALOG_PRICE_RE.match(text or ""))

def dedupe_consecutive_exact_lines(lines):
    """
    Collapse only adjacent, exactly identical non-empty rows.

    This is intentionally stricter than general deduplication: if the same
    product genuinely appears again later in the source, it is retained.
    """
    output = []
    previous_nonempty = None

    for line in lines:
        text = line.strip()

        if not text:
            output.append(line)
            continue

        if previous_nonempty == text:
            continue

        output.append(line)
        previous_nonempty = text

    return output

def parse_catalog_product_line(line):
    """
    Parse one product row from the observed shop/catalog format:

        Brewery [x Collaborator] - Beer Name Double New England IPA

    The structural separator requires whitespace before the hyphen, so an
    internal brewery hyphen such as "Bas-Canada" is preserved. Whitespace after
    the structural hyphen is optional, covering "Tall Trees -Virditas".
    """
    text = collapse_exact_doubled_line(
        strip_bullet(line.strip())
    )

    if not text or is_catalog_price_line(text):
        return None

    # Structural separator: require whitespace before "-", but not after it.
    # This avoids splitting "Bas-Canada".
    match = re.match(
        r"^(?P<brewery>.+?)\s+-\s*(?P<rest>.+)$",
        text,
    )
    if not match:
        return None

    brewery = match.group("brewery").strip()
    rest = match.group("rest").strip()

    style_match = CATALOG_STYLE_RE.search(rest)
    if not style_match:
        return None

    beer = rest[:style_match.start()].strip()
    style = re.sub(
        r"\s{2,}",
        " ",
        style_match.group("style").strip(),
    )

    if not brewery or not beer:
        return None

    # A trailing alias after the style is catalog/page metadata. The observed
    # example is "Océanides ... - Oceanides"; it is intentionally not added
    # to the beer identity.
    return structured_menu_item(
        text,
        beer,
        brewery=brewery,
        style=style,
    )

def parse_catalog_menu_lines(lines):
    """
    Return parsed catalog products when the input strongly resembles the
    observed website format; otherwise return None so the normal parser runs.
    """
    cleaned = [
        collapse_exact_doubled_line(
            strip_bullet(line.rstrip("\n"))
        )
        for line in lines
    ]

    price_count = sum(
        1 for line in cleaned
        if is_catalog_price_line(line)
    )

    if price_count < 1:
        return None

    deduped = dedupe_consecutive_exact_lines(cleaned)

    products = []
    meaningful_nonprice = 0

    for line in deduped:
        text = line.strip()

        if not text or is_catalog_price_line(text):
            continue

        meaningful_nonprice += 1
        item = parse_catalog_product_line(text)

        if item:
            products.append(item)

    if meaningful_nonprice < 1:
        return None

    parse_ratio = len(products) / meaningful_nonprice

    # Conservative format gate:
    # - a one-product fixture with one price row must parse perfectly;
    # - larger catalog inputs retain v26's >=80% rule and require >=2 products.
    if price_count == 1:
        if len(products) == 1 and parse_ratio == 1.0:
            return products
        return None

    if (
        len(products) >= 2
        and parse_ratio >= 0.80
    ):
        return products

    return None

def parse_tabular_menu_lines(lines):
    """Parse a tab-separated ``brewery / beer / ABV / style`` menu.

    The adapter is deliberately strict: every non-empty row must contain
    exactly four tab-delimited fields, and field 3 must be an exact ABV
    percentage. If any row fails that shape, return None so the existing
    parser handles the input unchanged.
    """
    rows = []

    for raw in lines:
        text = raw.rstrip("\n")
        if not text.strip():
            continue

        parts = [part.strip() for part in text.split("\t")]
        if len(parts) != 4:
            return None

        brewery, beer, abv_text, style = parts
        if not brewery or not beer:
            return None

        abv_match = re.fullmatch(
            r"(\d+(?:[.,]\d+)?)\s*%\s*(?:abv)?",
            abv_text,
            re.IGNORECASE,
        )
        if not abv_match:
            return None

        try:
            menu_abv = float(abv_match.group(1).replace(",", "."))
        except ValueError:
            return None

        # The columns already define identity and metadata explicitly, so do
        # not run the beer field through generic style/noise stripping. That
        # would incorrectly alter legitimate names such as ``Élixir-IPA``.
        beer = beer.strip()
        brewery = brewery.strip()
        style = style.strip() or None

        if len(normalize(beer)) < 3:
            return None

        rows.append({
            "original": text.strip(),
            "brewery": brewery,
            "beer": beer,
            "style": style,
            "menu_abv": menu_abv,
            "query": join_brewery_and_beer(brewery, beer),
        })

    return rows if rows else None

def parse_menu_lines(lines):
    """
    Stateful menu parser.

    It understands common brewery-first layouts and trailing-brewery records:

        Oktoberfest (2026)
        Festbier / Wiesnbier | 6%
        Sierra Nevada Brewing Co.

    Brewery context persists until another likely brewery heading appears.
    Style/section headings are remembered as parsing context but are not added
    to the Untappd query.
    """

    # v45: first try the narrowly gated four-column tabular adapter.
    tabular_items = parse_tabular_menu_lines(lines)
    if tabular_items is not None:
        return tabular_items

    # v26: then try the narrowly gated website-catalog adapter.
    catalog_items = parse_catalog_menu_lines(lines)
    if catalog_items is not None:
        return catalog_items

    raw_lines = [
        collapse_exact_doubled_line(
            strip_bullet(line.rstrip("\n"))
        )
        for line in lines
    ]

    parsed = []
    current_brewery = None
    current_style = None
    pending_plain = None
    pending_trailing = None

    def flush_pending():
        nonlocal pending_plain

        if not pending_plain:
            return

        item = structured_menu_item(
            pending_plain,
            pending_plain,
            brewery=current_brewery,
            style=current_style,
        )

        if item:
            parsed.append(item)

        pending_plain = None

    def flush_trailing_without_brewery():
        nonlocal pending_trailing

        if not pending_trailing:
            return

        item = structured_menu_item(
            pending_trailing["original"],
            pending_trailing["beer"],
            brewery=current_brewery,
            style=pending_trailing.get("style"),
            menu_abv=pending_trailing.get("menu_abv"),
        )

        if item:
            parsed.append(item)

        pending_trailing = None

    for idx, line in enumerate(raw_lines):
        text = line.strip()

        if not text:
            continue

        next_nonempty = None
        for later in raw_lines[idx + 1:]:
            if later.strip():
                next_nonempty = later.strip()
                break

        # Complete a previously recognized Beer -> Style/ABV -> Brewery row.
        if pending_trailing:
            if looks_like_brewery_heading(text):
                brewery = final_query_cleanup(text)

                item = structured_menu_item(
                    pending_trailing["original"],
                    pending_trailing["beer"],
                    brewery=brewery,
                    style=pending_trailing.get("style"),
                    menu_abv=pending_trailing.get("menu_abv"),
                )

                if item:
                    parsed.append(item)

                current_brewery = brewery
                current_style = None
                pending_trailing = None
                continue

            flush_trailing_without_brewery()

        if looks_like_menu_noise_line(text):
            continue

        if is_style_heading(text):
            flush_pending()
            current_style = text
            continue

        metadata_context = parse_metadata_context(text)

        if metadata_context:
            if pending_plain:
                item = structured_menu_item(
                    pending_plain,
                    pending_plain,
                    brewery=(
                        metadata_context.get("brewery")
                        or current_brewery
                    ),
                    style=current_style,
                    menu_abv=metadata_context.get("abv"),
                )

                if item:
                    parsed.append(item)

                if metadata_context.get("brewery"):
                    current_brewery = metadata_context["brewery"]

                pending_plain = None
                continue

            if metadata_context.get("brewery"):
                current_brewery = metadata_context["brewery"]
            continue

        if is_metadata_only(text):
            flush_pending()
            continue

        has_inline_metadata = bool(
            re.search(
                r"(?:\d+(?:[.,]\d+)?\s*%|\bibu\b|\b\d+(?:[.,]\d+)?\s*(?:ml|cl|oz)\b|€|\$|£)",
                text,
                re.IGNORECASE,
            )
        )

        # v22: only reinterpret Style | ABV as a continuation when there is
        # already a pending beer and the following line looks like a brewery.
        trailing_style = None
        if (
            pending_plain
            and next_nonempty
            and looks_like_brewery_heading(next_nonempty)
        ):
            trailing_style = parse_trailing_style_abv(text)

        if trailing_style:
            pending_trailing = {
                "original": pending_plain,
                "beer": pending_plain,
                "style": trailing_style["style"],
                "menu_abv": trailing_style["abv"],
            }
            pending_plain = None
            continue

        brewery_signal = looks_like_brewery_heading(text)

        if brewery_signal and has_inline_metadata:
            brewery_signal = False

        if (
            brewery_signal
            and next_nonempty
            and is_metadata_only(next_nonempty)
        ):
            brewery_signal = False

        if brewery_signal:
            flush_pending()
            current_brewery = final_query_cleanup(text)
            current_style = None
            continue

        if has_inline_metadata:
            flush_pending()
            item = structured_menu_item(
                text,
                text,
                brewery=current_brewery,
                style=current_style,
            )

            if item:
                parsed.append(item)

            continue

        if re.search(r"\s(?:\||—|–)\s", text):
            flush_pending()
            item = structured_menu_item(
                text,
                text,
                brewery=current_brewery,
                style=current_style,
            )

            if item:
                parsed.append(item)

            continue

        if pending_plain:
            flush_pending()

        pending_plain = text

    if pending_trailing:
        flush_trailing_without_brewery()

    flush_pending()
    return parsed


# ============================================================
# v56 format detection and validation
# ============================================================

FORMAT_TABULAR = "tab-separated"
FORMAT_TRAILING_BREWERY = "beer-style-abv-brewery"
FORMAT_DOUBLE_SLASH = "beer-double-slash-abv-style"
FORMAT_CATALOG = "webshop-catalog"
FORMAT_BREWERY_BLOCK = "brewery-heading-block"
FORMAT_METADATA_PAIRS = "beer-metadata-pairs"
FORMAT_TAP_LIST = "tap-list-blocks"

FORMAT_DISPLAY_NAMES = {
    FORMAT_TABULAR: "Tab-separated rows",
    FORMAT_TRAILING_BREWERY: "Beer / Style + ABV / Brewery records",
    FORMAT_DOUBLE_SLASH: "Beer // ABV // Style records",
    FORMAT_CATALOG: "Supported webshop/catalog rows",
    FORMAT_BREWERY_BLOCK: "Brewery-heading blocks",
    FORMAT_METADATA_PAIRS: "Beer/style + ABV/IBU/brewery pairs",
    FORMAT_TAP_LIST: "Tap-list blocks",
}


NORMALIZED_RECORD_FIELDS = (
    "brewery",
    "beer",
    "style",
    "menu_abv",
    "query",
    "original",
)


class MenuValidationError(ValueError):
    """Raised when a raw menu or its normalized records fail validation."""


def menu_format_display_name(format_name):
    return FORMAT_DISPLAY_NAMES.get(format_name, str(format_name))


def _nonempty_raw_lines(lines):
    return [line.rstrip("\n") for line in lines if line.strip()]


def _metadata_line_with_brewery(line):
    context = parse_metadata_context(line.strip())
    return bool(context and context.get("brewery"))


def _looks_like_brewery_block(lines):
    raw = _nonempty_raw_lines(lines)
    if not raw:
        return False

    saw_heading = False
    saw_beer = False
    current_brewery = None

    for line in raw:
        text = collapse_exact_doubled_line(strip_bullet(line)).strip()
        if looks_like_brewery_heading(text) and extract_menu_abv(text) is None:
            current_brewery = text
            saw_heading = True
            continue

        if current_brewery is None or extract_menu_abv(text) is None:
            return False
        if _metadata_line_with_brewery(text) or looks_like_menu_noise_line(text):
            return False
        saw_beer = True

    return saw_heading and saw_beer


def _looks_like_metadata_pairs(lines):
    raw = _nonempty_raw_lines(lines)
    if len(raw) < 2 or len(raw) % 2:
        return False

    for offset in range(0, len(raw), 2):
        beer_line = collapse_exact_doubled_line(strip_bullet(raw[offset])).strip()
        metadata_line = collapse_exact_doubled_line(strip_bullet(raw[offset + 1])).strip()
        if is_metadata_only(beer_line) or looks_like_menu_noise_line(beer_line):
            return False
        if not _metadata_line_with_brewery(metadata_line):
            return False
    return True


def _looks_like_tap_list(lines):
    raw = _nonempty_raw_lines(lines)
    if not raw:
        return False
    if not any(looks_like_menu_noise_line(line) for line in raw):
        return False
    return any(_metadata_line_with_brewery(line) for line in raw)


def detect_menu_format(lines):
    """Detect one deliberately supported raw menu format.

    Detection is intentionally structural. Once a strong format signal is
    present (tabs, catalog price rows, or ``//`` separators), that format owns
    the file and validation decides whether the file is well formed. A
    malformed strongly-recognized file is never silently reinterpreted by the
    legacy/stateful parser.
    """
    raw = _nonempty_raw_lines(lines)
    if not raw:
        raise MenuValidationError("The menu file is empty.")

    if any("\t" in line for line in raw):
        return FORMAT_TABULAR

    if any(is_catalog_price_line(line.strip()) for line in raw):
        return FORMAT_CATALOG

    if any("//" in line for line in raw):
        return FORMAT_DOUBLE_SLASH

    # These v76 adapters are deliberately recognized before the older
    # three-line form. Their metadata can contain the same separators, but
    # their record boundaries are different and more specific.
    if _looks_like_tap_list(raw):
        return FORMAT_TAP_LIST

    if _looks_like_metadata_pairs(raw):
        return FORMAT_METADATA_PAIRS

    if _looks_like_brewery_block(raw):
        return FORMAT_BREWERY_BLOCK

    # The three-line form is the least syntactically distinctive, so only
    # claim it when at least one Style | ABV continuation is visible.
    if any(parse_trailing_style_abv(line.strip()) for line in raw):
        return FORMAT_TRAILING_BREWERY

    raise MenuValidationError(
        "The input does not match a supported raw menu format."
    )


def _validate_tabular_raw(lines):
    for line_number, raw in enumerate(lines, start=1):
        text = raw.rstrip("\n")
        if not text.strip():
            continue

        parts = [part.strip() for part in text.split("\t")]
        if len(parts) != 4:
            raise MenuValidationError(
                f"Line {line_number} has {len(parts)} tab-separated fields; "
                "expected exactly 4: brewery<TAB>beer<TAB>ABV<TAB>style."
            )

        brewery, beer, abv_text, _style = parts
        if not brewery:
            raise MenuValidationError(
                f"Line {line_number} has an empty brewery field."
            )
        if not beer:
            raise MenuValidationError(
                f"Line {line_number} has an empty beer field."
            )
        if not re.fullmatch(
            r"(\d+(?:[.,]\d+)?)\s*%\s*(?:abv)?",
            abv_text,
            re.IGNORECASE,
        ):
            raise MenuValidationError(
                f"Line {line_number} has invalid ABV {abv_text!r}; "
                "expected a percentage such as 6.5%."
            )


def _validate_catalog_raw(lines):
    cleaned = [
        collapse_exact_doubled_line(strip_bullet(line.rstrip("\n")))
        for line in lines
    ]
    deduped = dedupe_consecutive_exact_lines(cleaned)

    price_count = sum(1 for line in deduped if is_catalog_price_line(line))
    if price_count < 1:
        raise MenuValidationError(
            "Catalog format was detected but no supported price row was found."
        )

    product_count = 0
    for line_number, text in enumerate(deduped, start=1):
        text = text.strip()
        if not text or is_catalog_price_line(text):
            continue
        if parse_catalog_product_line(text) is None:
            raise MenuValidationError(
                f"Catalog line {line_number} is not a supported product row: "
                f"{text!r}."
            )
        product_count += 1

    if product_count < 1:
        raise MenuValidationError(
            "Catalog format was detected but no product rows could be parsed."
        )


def _validate_double_slash_raw(lines):
    for line_number, raw in enumerate(lines, start=1):
        text = collapse_exact_doubled_line(strip_bullet(raw.rstrip("\n"))).strip()
        if not text:
            continue
        parsed = parse_double_slash_beer_metadata(text)
        if parsed is None:
            raise MenuValidationError(
                f"Line {line_number} is not valid Beer // ABV // Style input: "
                f"{text!r}."
            )
        if len(normalize(parsed["beer"])) < 3:
            raise MenuValidationError(
                f"Line {line_number} has an empty or too-short beer name."
            )


def _validate_trailing_brewery_raw(lines):
    raw = [
        collapse_exact_doubled_line(strip_bullet(line.rstrip("\n"))).strip()
        for line in lines
        if line.strip()
    ]

    if len(raw) % 3 != 0:
        raise MenuValidationError(
            "Beer / Style + ABV / Brewery input must contain complete "
            "three-line records."
        )

    for offset in range(0, len(raw), 3):
        beer, style_abv, brewery = raw[offset:offset + 3]
        record_number = offset // 3 + 1

        if not beer or is_metadata_only(beer):
            raise MenuValidationError(
                f"Record {record_number} has an invalid beer-name line."
            )

        if parse_trailing_style_abv(style_abv) is None:
            raise MenuValidationError(
                f"Record {record_number} has invalid Style | ABV metadata: "
                f"{style_abv!r}."
            )

        if not looks_like_brewery_heading(brewery):
            raise MenuValidationError(
                f"Record {record_number} has an unrecognized brewery line: "
                f"{brewery!r}."
            )


def _validate_brewery_block_raw(lines):
    raw = _nonempty_raw_lines(lines)
    current_brewery = None
    beer_count = 0

    for line_number, raw_line in enumerate(raw, start=1):
        text = collapse_exact_doubled_line(strip_bullet(raw_line)).strip()
        if looks_like_brewery_heading(text) and extract_menu_abv(text) is None:
            current_brewery = text
            continue

        if current_brewery is None:
            raise MenuValidationError(
                f"Brewery-heading line {line_number} appears before any brewery heading."
            )
        if extract_menu_abv(text) is None or _metadata_line_with_brewery(text):
            raise MenuValidationError(
                f"Brewery-heading line {line_number} is not a Beer — ABV row: {text!r}."
            )
        item = structured_menu_item(text, text, brewery=current_brewery)
        if item is None:
            raise MenuValidationError(
                f"Brewery-heading line {line_number} has an invalid beer identity."
            )
        beer_count += 1

    if beer_count < 1:
        raise MenuValidationError(
            "Brewery-heading format was detected but no beer rows could be parsed."
        )


def _validate_metadata_pairs_raw(lines):
    raw = _nonempty_raw_lines(lines)
    if len(raw) % 2:
        raise MenuValidationError(
            "Beer/style + ABV/IBU/brewery input must contain complete two-line records."
        )

    for offset in range(0, len(raw), 2):
        beer_line = collapse_exact_doubled_line(strip_bullet(raw[offset])).strip()
        metadata_line = collapse_exact_doubled_line(strip_bullet(raw[offset + 1])).strip()
        record_number = offset // 2 + 1
        if is_metadata_only(beer_line) or looks_like_menu_noise_line(beer_line):
            raise MenuValidationError(
                f"Record {record_number} has an invalid beer/style line."
            )
        context = parse_metadata_context(metadata_line)
        if not context or not context.get("brewery") or context.get("abv") is None:
            raise MenuValidationError(
                f"Record {record_number} has invalid ABV/IBU/brewery metadata: "
                f"{metadata_line!r}."
            )


def _validate_tap_list_raw(lines):
    raw = _nonempty_raw_lines(lines)
    index = 0
    record_count = 0
    saw_display_metadata = False

    while index < len(raw):
        beer_line = collapse_exact_doubled_line(strip_bullet(raw[index])).strip()
        if is_metadata_only(beer_line) or looks_like_menu_noise_line(beer_line):
            raise MenuValidationError(
                f"Tap-list record {record_count + 1} has an invalid beer/style line: "
                f"{beer_line!r}."
            )
        if index + 1 >= len(raw):
            raise MenuValidationError(
                "Tap-list input ends before the ABV/IBU/brewery metadata line."
            )

        metadata_line = collapse_exact_doubled_line(strip_bullet(raw[index + 1])).strip()
        context = parse_metadata_context(metadata_line)
        if not context or not context.get("brewery") or context.get("abv") is None:
            raise MenuValidationError(
                f"Tap-list record {record_count + 1} has invalid ABV/IBU/brewery "
                f"metadata: {metadata_line!r}."
            )

        record_count += 1
        index += 2
        while index < len(raw) and looks_like_menu_noise_line(raw[index]):
            saw_display_metadata = True
            index += 1

    if record_count < 1 or not saw_display_metadata:
        raise MenuValidationError(
            "Tap-list format requires at least one complete beer block and one "
            "display-rating or serving/price row."
        )


def validate_raw_menu(lines, format_name=None):
    """Validate raw input against one supported format and return its name."""
    lines = list(lines)
    format_name = format_name or detect_menu_format(lines)

    if format_name == FORMAT_TABULAR:
        _validate_tabular_raw(lines)
    elif format_name == FORMAT_CATALOG:
        _validate_catalog_raw(lines)
    elif format_name == FORMAT_DOUBLE_SLASH:
        _validate_double_slash_raw(lines)
    elif format_name == FORMAT_TRAILING_BREWERY:
        _validate_trailing_brewery_raw(lines)
    elif format_name == FORMAT_BREWERY_BLOCK:
        _validate_brewery_block_raw(lines)
    elif format_name == FORMAT_METADATA_PAIRS:
        _validate_metadata_pairs_raw(lines)
    elif format_name == FORMAT_TAP_LIST:
        _validate_tap_list_raw(lines)
    else:
        raise MenuValidationError(f"Unsupported menu format: {format_name!r}.")

    return format_name


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


def validate_and_parse_menu_lines(
    lines: Iterable[str],
) -> Tuple[str, List[NormalizedMenuRecord]]:
    """Validate raw input, parse it, then validate normalized records.

    Returns ``(format_name, items)``. No network/browser behavior exists in
    this module, making this the local preflight boundary before Untappd work.
    """
    lines = list(lines)
    format_name = validate_raw_menu(lines)

    if format_name == FORMAT_TABULAR:
        items = parse_tabular_menu_lines(lines)
    elif format_name == FORMAT_CATALOG:
        items = parse_catalog_menu_lines(lines)
    else:
        # The stateful parser contains the established normalization behavior
        # for the two human-readable structured formats. Raw validation above
        # guarantees that unsupported text cannot fall through into it.
        items = parse_menu_lines(lines)

    validate_normalized_menu(items)
    return format_name, cast(List[NormalizedMenuRecord], items)


def read_validated_menu(
    filename: str,
) -> Tuple[str, List[NormalizedMenuRecord]]:
    with open(filename, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return validate_and_parse_menu_lines(lines)

def read_menu(filename):
    with open(
        filename,
        "r",
        encoding="utf-8",
    ) as f:
        lines = f.readlines()

    return parse_menu_lines(lines)

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
