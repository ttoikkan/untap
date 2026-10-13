"""Pure shared policy for review identity, row order and selectable candidates.

No HTML, persistence, candidate retrieval or selection mutation belongs here.
"""
import hashlib
import json
from typing import Any, List, Optional, Sequence

from untap.types import AlternativeRecord, MatchResult

DEFAULT_REPORT_TITLE = "Untap Results"


def selection_report_id(results: Sequence[MatchResult], title: str, report_date: str) -> str:
    payload = {"results": results, "title": title.strip() or DEFAULT_REPORT_TITLE, "date": report_date}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def review_candidates(result: MatchResult) -> List[AlternativeRecord]:
    raw = result.get("same_abv_variants") or result.get("alternatives") or []
    candidates = list(raw)
    candidates.sort(
        key=lambda item: (
            -(float(item.get("score") or 0)),
            str(item.get("name") or "").casefold(),
        )
    )
    return [item for item in candidates if not item.get("user_added")][:10] + [
        item for item in candidates if item.get("user_added")]


def _rating_value(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def result_sort_rating(result: MatchResult) -> Optional[float]:
    """Return the rating used only to position one top-level report result."""
    if result.get("status") == "ok":
        return _rating_value(result.get("rating"))

    candidates = review_candidates(result)
    if not candidates:
        return None
    return _rating_value(candidates[0].get("rating"))


def sorted_review_results(results: Sequence[MatchResult]) -> List[MatchResult]:
    ordered = list(results)
    ordered.sort(
        key=lambda result: (
            result_sort_rating(result) is not None,
            result_sort_rating(result) or 0.0,
        ),
        reverse=True,
    )
    return ordered


def available_review_candidate(result: MatchResult, url: Any) -> Optional[AlternativeRecord]:
    """Return an allowed choice, retaining the existing selection URL contract.

    Excluded inspection evidence is never a choice. Failed rows require an
    explicitly retrieved candidate before they become reviewable.
    """
    if (result.get("status") not in ("ambiguous", "ok")
            or not isinstance(url, str) or not url.startswith("https://untappd.com/b/")):
        return None
    return next((candidate for candidate in review_candidates(result)
                 if candidate.get("url") == url), None)
