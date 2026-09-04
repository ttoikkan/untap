"""Shared static contracts for Untap module boundaries.

These TypedDicts describe dictionary-shaped records that already existed at
runtime before v63.  They are type-checking aids only: they do not replace the
runtime validators or change serialized data.
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict, Union


MatchStatus = Literal[
    "ok",
    "ambiguous",
    "low_confidence",
    "failed",
    "rate_limited",
]


class NormalizedMenuRecord(TypedDict):
    """Validated parser output consumed by the matcher/batch boundary."""

    brewery: Optional[str]
    beer: str
    style: Optional[str]
    menu_abv: Optional[float]
    query: str
    original: str


class CandidateRecord(TypedDict, total=False):
    """Matcher candidate fields used across scoring/ambiguity boundaries."""

    name: str
    url: str
    text: str
    score: float
    abv: Optional[float]
    brewery: Optional[str]
    rating_score: Optional[float]
    rating_count: Optional[int]
    type_name: Optional[str]
    image_url: Optional[str]
    image_hd_url: Optional[str]
    in_production: object
    object_id: str
    beer_id: Union[str, int]


class AlternativeRecord(TypedDict, total=False):
    """Compact candidate representation surfaced in ambiguous results."""

    name: str
    score: float
    abv: Optional[float]
    brewery: Optional[str]
    rating: Optional[float]
    ratings: Optional[int]
    type_name: Optional[str]
    url: Optional[str]
    image_url: Optional[str]
    image_hd_url: Optional[str]
    in_production: object


class MatchResult(TypedDict, total=False):
    """Matcher/batch result contract.

    The mapping is intentionally ``total=False`` because success, ambiguity,
    low-confidence, failure, and rate-limit results expose different subsets
    of the established runtime fields.
    """

    query: str
    status: MatchStatus
    reason: str
    http_status: int
    match: str
    score: float
    url: Optional[str]
    alternatives: List[AlternativeRecord]
    same_abv_variants: List[AlternativeRecord]
    search_expanded: bool
    search_fallback: Optional[str]
    expanded_total_hits: Optional[int]

    # Confirmed Untappd detail fields.
    beer: str
    brewery: str
    rating: Optional[float]
    ratings: Optional[int]
    abv: Union[str, float, None]
    ibu: Union[str, int, None]
    type_name: Optional[str]
    search_text: str
    image_url: Optional[str]
    image_hd_url: Optional[str]
    in_production: object

    # Batch/CSV persistence fields added after matching.
    original_menu_text: Optional[str]
    input_brewery: str
    input_beer: str
    input_abv: str
    input_style: str
    resumed: bool
    batch_remaining: int


CsvScalar = Union[str, float, int, None]


class CsvRow(TypedDict):
    """Stable persisted CSV schema from ``untap_batch.CSV_FIELDS``."""

    original_menu_text: CsvScalar
    input_brewery: CsvScalar
    input_beer: CsvScalar
    input_abv: CsvScalar
    input_style: CsvScalar
    query: CsvScalar
    status: CsvScalar
    beer: CsvScalar
    brewery: CsvScalar
    rating: CsvScalar
    ratings: CsvScalar
    abv: CsvScalar
    ibu: CsvScalar
    type_name: CsvScalar
    score: CsvScalar
    reason: CsvScalar
    alternatives: CsvScalar
    url: CsvScalar


class AlgoliaRequestRecord(TypedDict, total=False):
    """Normalized request entry captured from an Algolia multi-query POST."""

    indexName: Optional[str]
    query: Optional[str]
    page: Optional[str]
    hitsPerPage: Optional[str]
    filters: Optional[str]
    params: Dict[str, Any]


class AlgoliaTransportEvent(TypedDict, total=False):
    """Request/response event exchanged by the live Untappd transport."""

    kind: str
    method: str
    status: Optional[int]
    url: Optional[str]
    resource_type: str
    algolia_requests: List[AlgoliaRequestRecord]
    algolia_response: List[Dict[str, Any]]
    algolia_response_error: str
    headers: Dict[str, str]


class SearchTransportResult(TypedDict):
    """Page-zero search transport result consumed by the matcher."""

    request_event: Optional[AlgoliaTransportEvent]
    events: List[AlgoliaTransportEvent]
    error: Optional[str]
    transport: str
