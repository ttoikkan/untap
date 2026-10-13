"""Pure, HTML-free presentation data for report cards."""
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from untap.types import MatchResult
from untap.review_policy import review_candidates, result_sort_rating
from untap.snapshot import menu_item_ids


def format_rating(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def format_count(value: Any) -> str:
    if value is None or value == "":
        return "N/A"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def format_abv(value: Any) -> str:
    if value is None or value == "":
        return "N/A"
    if isinstance(value, (int, float)):
        return f"{value:g}%"
    text = str(value).strip()
    return text if text.endswith("%") else f"{text}%"


def production_label(value: Any) -> Optional[str]:
    is_false = value is False or (
        not isinstance(value, bool) and isinstance(value, (int, float)) and value == 0
    ) or (isinstance(value, str) and value.strip().casefold() in {"0", "false"})
    is_true = value is True or (
        not isinstance(value, bool) and isinstance(value, (int, float)) and value == 1
    ) or (isinstance(value, str) and value.strip().casefold() in {"1", "true"})
    if is_false:
        return "Listed as out of production on Untappd"
    if is_true:
        return "Listed as in production on Untappd"
    return None


@dataclass(frozen=True)
class NameLink:
    name: str
    url: object


@dataclass(frozen=True)
class BeerView:
    name: str
    url: object
    brewery: str
    abv: str
    type_name: object
    rating: str
    ratings: str
    image_url: object
    image_hd_url: object
    production: Optional[str]
    score: str
    notes: Tuple[str, ...]
    abv_mismatch: bool


@dataclass(frozen=True)
class ExcludedView:
    link: NameLink
    brewery: object
    abv: str
    reason: str


@dataclass(frozen=True)
class ReportRow:
    item_id: str
    confirmed: Optional[BeerView]
    status: str
    status_key: str
    query: str
    reason: str
    menu_abv: str
    search_warning: Optional[str]
    initial_selection: str
    automatic_selection: str
    candidates: Tuple[BeerView, ...]
    best_guess: Optional[NameLink]
    excluded: Tuple[ExcludedView, ...]


def _beer_view(record: Mapping[str, Any], name: Any, result: Optional[MatchResult] = None) -> BeerView:
    notes: List[str] = []
    mismatch = False
    user_added = bool(record.get("user_added")) if result is not None else False
    score = record.get("score") if result is not None else None
    score_text = f"{float(score):.3f}" if score is not None else "N/A"
    if user_added and result is not None:
        notes.extend(("User-added candidate — verify against the menu.",
                      f"Check against menu: {result.get('input_brewery') or 'Unknown brewery'} · "
                      f"{result.get('input_abv') or 'Unknown'}% ABV"))
        try:
            menu_abv = float(str(result.get("input_abv")).rstrip("%").replace(",", "."))
            candidate_abv = float(str(record.get("abv")).rstrip("%").replace(",", "."))
            mismatch = abs(menu_abv - candidate_abv) > .05
        except (TypeError, ValueError):
            notes.append("ABV comparison unavailable — verify before confirming.")
    return BeerView(str(name or ""), record.get("url"), str(record.get("brewery") or "Unknown brewery"),
                    format_abv(record.get("abv")), record.get("type_name"),
                    format_rating(record.get("rating")), format_count(record.get("ratings")),
                    record.get("image_url"), record.get("image_hd_url"),
                    production_label(record.get("in_production")),
                    "User-added" if user_added else "Match " + score_text,
                    tuple(notes), mismatch)


def prepare_report_rows(results: Sequence[MatchResult]) -> List[ReportRow]:
    """Prepare display decisions without HTML or modifying saved results."""
    identifiers = menu_item_ids(results)
    ordered = sorted(enumerate(results), key=lambda row: (
        result_sort_rating(row[1]) is not None, result_sort_rating(row[1]) or 0.0), reverse=True)
    rows = []
    for index, result in ordered:
        candidates = review_candidates(result)
        simple = (result.get("status") == "ok" and not result.get("manually_confirmed")
                  and not any(c.get("url") != result.get("url") for c in candidates))
        confirmed = _beer_view(result, result.get("beer")) if simple else None
        views = () if simple else tuple(_beer_view(c, c.get("name"), result) for c in candidates)
        best = (NameLink(str(result.get("match")), result.get("url"))
                if not simple and not views and result.get("match") else None)
        excluded = () if simple else tuple(ExcludedView(
            NameLink(str(c.get("name") or ""), c.get("url")), c.get("brewery"),
            format_abv(c.get("abv")), str(c.get("exclusion_reason") or "Identity conflict"))
            for c in result.get("excluded_candidates") or [])
        status = str(result.get("status") or "unknown")
        manual = bool(result.get("manually_confirmed"))
        selected = str(result.get("url") or "") if status == "ok" else ""
        rows.append(ReportRow(identifiers[index], confirmed,
            "Ambiguous" if manual else status.replace("_", " ").title(),
            "ambiguous" if manual else status,
            str(result.get("query") or result.get("input_beer") or "Untap result"),
            str(result.get("reason") or ("Match is ambiguous" if status == "ambiguous" else "Match unresolved")),
            format_abv(result.get("input_abv")),
            str(result["search_warning"]) if result.get("search_warning") else None,
            selected, selected if not manual else "", views, best, excluded))
    return rows
