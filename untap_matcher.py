import re
from difflib import SequenceMatcher
from typing import Any, Dict, Optional, TypedDict
from time import perf_counter

from untap_types import AlternativeRecord, CandidateRecord, MatchResult, SearchTransportResult

from untap_parser import (
    normalize,
    clean_block_text,
    final_query_cleanup,
    collaboration_brewery_for_search,
    COLLABORATION_SEPARATOR_RE,
)
from untap_untappd import (
    RATE_LIMIT_HTTP_STATUS,
    MAX_ALGOLIA_EXPANSION_PAGES,
    ABV_DESC_ALGOLIA_INDEX,
    _ALGOLIA_DEBUG_STATS,
    _fetch_algolia_page,
    _reset_beer_algolia_debug_stats,
    _note_algolia_request,
    _print_algolia_network_summary,
    _fetch_algolia_sorted_page,
    _matching_algolia_response_status,
    _matching_algolia_nb_hits,
    _matching_algolia_initial_page,
    extract_beer_info,
    debug_timing_enabled,
    open_search_box,
    start_search_network_capture,
    stop_search_network_capture,
    submit_search,
    shadow_compare_search_transport,
    fetch_authoritative_algolia_search,
    remember_search_transport_template,
    invalidate_search_transport_template,
    note_search_transport_recovery,
    search_transport_template_available,
)

# ============================================================
# Untappd matcher
# ============================================================
# v58: matching decisions remain here; browser/Algolia transport primitives moved
# to untap_untappd.py without intended behavior changes.
# Matching, scoring, fallback, ambiguity, Algolia, metadata-recovery, and
# HTTP-429 behavior are intentionally unchanged.

DEFAULT_MIN_SCORE = 0.425
MATCH_RESULT_STATUSES = frozenset({
    "ok",
    "ambiguous",
    "low_confidence",
    "failed",
    "rate_limited",
})

MAX_RAW_CANDIDATE_SCORE = 1.60
AMBIGUITY_SCORE_MARGIN = 0.03
FAMILY_MIN_WORDS = 2
# Complete Algolia expansion is a diagnostic/recovery path, not a bulk index
# crawler. At Untappd's observed 5 hits/page, 20 pages examines up to 100 hits
# while preventing pathological one-word fallbacks from issuing hundreds or
# thousands of requests.
ABV_DESCENDING_SCAN_MIN = 8.0
UNDERSPECIFIED_EARLY_STOP_MIN_EXACT_ABV_BEERS = 3

# score_candidate() weighting. Values are unchanged from v17 -- only their
# names are new -- so scoring behavior and DEFAULT_MIN_SCORE are unaffected.
WORD_SCORE_WEIGHT = 0.50
NAME_SCORE_WEIGHT = 0.50
ALL_WORDS_MATCHED_BONUS = 0.15
BREWERY_MATCH_WEIGHT = 0.20
BREWERY_NO_MATCH_PENALTY = 0.20
ABV_CLOSE_DIFF = 0.15
EXACT_ABV_FAMILY_BONUS = 0.04
EXACT_ABV_EPSILON = 0.01
ABV_CLOSE_BONUS = 0.25
ABV_NEAR_DIFF = 0.50
ABV_NEAR_BONUS = 0.10
ABV_MISMATCH_DIFF = 1.00
ABV_MISMATCH_PENALTY = 0.40

# Narrow human-typo support for beer names.
BEER_NAME_TYPO_BONUS = 0.10
MIN_TYPO_TOKEN_LENGTH = 7





# ============================================================
# Text helpers
# ============================================================



def similarity(a, b):
    return SequenceMatcher(
        None,
        normalize(a),
        normalize(b),
    ).ratio()


def levenshtein_distance_exactly_one(a, b):
    """Return True only when two strings have edit distance exactly 1."""
    if a == b:
        return False

    if abs(len(a) - len(b)) > 1:
        return False

    if len(a) == len(b):
        differences = sum(
            1
            for left, right in zip(a, b)
            if left != right
        )
        return differences == 1

    shorter, longer = (
        (a, b)
        if len(a) < len(b)
        else (b, a)
    )

    i = 0
    j = 0
    skipped = False

    while i < len(shorter) and j < len(longer):
        if shorter[i] == longer[j]:
            i += 1
            j += 1
            continue

        if skipped:
            return False

        skipped = True
        j += 1

    return True


def is_narrow_beer_name_typo(expected_beer, candidate_name):
    """
    Recognize exactly one likely human typo without fuzzing qualifiers.

    The normalized names must have the same token count. All tokens must be
    identical except one long alphabetic token, and that token pair must have
    edit distance exactly 1. Digits therefore remain strict.
    """
    expected_tokens = normalize(expected_beer).split()
    candidate_tokens = normalize(candidate_name).split()

    if (
        not expected_tokens
        or len(expected_tokens) != len(candidate_tokens)
    ):
        return False

    differing = [
        (expected, candidate)
        for expected, candidate in zip(
            expected_tokens,
            candidate_tokens,
        )
        if expected != candidate
    ]

    if len(differing) != 1:
        return False

    expected, candidate = differing[0]

    if (
        not expected.isalpha()
        or not candidate.isalpha()
        or len(expected) < MIN_TYPO_TOKEN_LENGTH
        or len(candidate) < MIN_TYPO_TOKEN_LENGTH
    ):
        return False

    return levenshtein_distance_exactly_one(
        expected,
        candidate,
    )











# ============================================================
# Menu parsing
# ============================================================
































































# ============================================================
# Untappd result matching
# ============================================================

def extract_abv_number(text):
    match = re.search(
        r"(\d+(?:[.,]\d+)?)%\s*ABV",
        text,
        re.IGNORECASE,
    )

    if not match:
        return None

    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def score_candidate(
    query,
    name,
    block_text,
    expected_beer=None,
    expected_brewery=None,
    expected_abv=None,
):
    query_norm = normalize(query)
    name_norm = normalize(name)
    block_norm = normalize(block_text)

    query_words = {
        word
        for word in query_norm.split()
        if len(word) >= 3
    }

    matched_words = sum(
        1
        for word in query_words
        if word in block_norm
    )

    word_score = (
        matched_words / len(query_words)
        if query_words
        else 0
    )

    # Compare the Untappd beer name primarily with the parsed beer field,
    # not with the combined brewery + beer search query.
    beer_target = expected_beer or query
    name_score = similarity(
        beer_target,
        name,
    )

    score = (
        word_score * WORD_SCORE_WEIGHT
        + name_score * NAME_SCORE_WEIGHT
    )

    if word_score == 1:
        score += ALL_WORDS_MATCHED_BONUS

    # Supporting evidence for one likely human typo in a long alphabetic
    # beer-name token. Numeric/year/version qualifiers remain exact.
    if is_narrow_beer_name_typo(
        beer_target,
        name,
    ):
        score += BEER_NAME_TYPO_BONUS

    # Brewery is an identity signal, not something we rank.
    if expected_brewery:
        brewery_words = {
            word
            for word in normalize(expected_brewery).split()
            if len(word) >= 3
            and word not in {"brew", "brewing", "brewery", "company"}
        }

        if brewery_words:
            brewery_matches = sum(
                1
                for word in brewery_words
                if word in block_norm
            )
            brewery_score = brewery_matches / len(brewery_words)
            score += BREWERY_MATCH_WEIGHT * brewery_score

            if brewery_score == 0:
                score -= BREWERY_NO_MATCH_PENALTY

    # ABV is an especially strong verification hint on messy menus.
    # A large mismatch should prevent a same-name beer from winning merely
    # because its text similarity is high.
    candidate_abv = extract_abv_number(block_text)

    if expected_abv is not None and candidate_abv is not None:
        diff = abs(expected_abv - candidate_abv)

        if diff <= ABV_CLOSE_DIFF:
            score += ABV_CLOSE_BONUS
        elif diff <= ABV_NEAR_DIFF:
            score += ABV_NEAR_BONUS
        elif diff >= ABV_MISMATCH_DIFF:
            score -= ABV_MISMATCH_PENALTY

    # Normalize the historical additive score to a 0.0-1.0 confidence
    # scale. Dividing by a constant preserves candidate ordering while
    # making debug output and --min-score easier to interpret.
    normalized_score = score / MAX_RAW_CANDIDATE_SCORE

    return max(0.0, min(1.0, normalized_score))


def extract_brewery_from_result(block_text, beer_name):
    lines = [
        line.strip()
        for line in block_text.splitlines()
        if line.strip()
    ]

    if not lines:
        return "Unknown"

    beer_norm = normalize(beer_name)

    for line in lines:
        if normalize(line) == beer_norm:
            continue

        if re.search(
            r"%\s*ABV",
            line,
            re.IGNORECASE,
        ):
            continue

        if re.search(
            r"\bIBU\b",
            line,
            re.IGNORECASE,
        ):
            continue

        if re.fullmatch(
            r"\(\d\.\d{1,3}\)",
            line,
        ):
            continue

        line_norm = normalize(line)

        if any(
            style in line_norm
            for style in [
                "ipa",
                "lager",
                "pilsner",
                "stout",
                "porter",
                "sour",
                "ale",
                "barleywine",
                "lambic",
                "farmhouse",
                "wheat beer",
                "kolsch",
            ]
        ):
            continue

        return line

    return "Unknown"












def _algolia_hit_to_candidate(hit):
    if not isinstance(hit, dict):
        return None

    beer_name = (hit.get("beer_name") or "").strip()
    brewery_name = (hit.get("brewery_name") or "").strip()

    if not beer_name:
        return None

    bid = hit.get("bid")
    slug = (hit.get("beer_slug") or "").strip()

    url = None
    if slug and bid:
        url = f"https://untappd.com/b/{slug}/{bid}"

    abv = hit.get("beer_abv")
    try:
        abv = float(abv) if abv is not None else None
    except Exception:
        abv = None

    block_parts = [brewery_name, beer_name]
    if abv is not None:
        block_parts.append(f"{abv:g}% ABV")

    block_text = " ".join(part for part in block_parts if part)

    return {
        "name": beer_name,
        "brewery": brewery_name,
        "text": block_text,
        "abv": abv,
        "url": url,
        "href": url,
        "bid": bid,
        "rating_score": hit.get("rating_score"),
        "rating_count": hit.get("rating_count"),
        "type_name": hit.get("type_name"),
        "ibu": hit.get("beer_ibu"),
        "source": "algolia",
    }




# Debug-only Algolia traffic accounting. Searches run serially, so a small
# process-local counter keeps the instrumentation isolated from matching logic.










def _underspecified_brewery_ambiguity_candidates(
    candidates,
    expected_beer,
    expected_brewery,
    expected_abv,
    min_score,
):
    """
    Return exact-ABV candidates proving a brewery-like input is under-specified.

    This is intentionally narrow and ambiguity-only. It applies only when the
    parser did not provide a separate brewery, the expected "beer" text has at
    least two words, and those words form the leading identity of a candidate
    brewery (for example ``Twin Elephant`` -> ``Twin Elephant Brewing Company``).
    Three distinct credible exact-ABV beers from that same brewery are enough to
    establish that the menu lacks a unique beer identifier.
    """
    if expected_brewery or expected_abv is None or not expected_beer:
        return []

    expected_words = normalize(expected_beer).split()
    if len(expected_words) < 2:
        return []

    groups = {}
    for candidate in candidates:
        brewery = (candidate.get("brewery") or "").strip()
        name = (candidate.get("name") or "").strip()
        abv = candidate.get("abv")
        if not brewery or not name or abv is None:
            continue
        if candidate.get("score", 0) < min_score:
            continue
        try:
            if abs(float(abv) - float(expected_abv)) > EXACT_ABV_EPSILON:
                continue
        except Exception:
            continue

        brewery_words = normalize(brewery).split()
        if brewery_words[: len(expected_words)] != expected_words:
            continue

        brewery_key = normalize(brewery)
        groups.setdefault(brewery_key, []).append(candidate)

    qualifying = []
    for group in groups.values():
        unique_names = {normalize(item.get("name") or "") for item in group}
        if len(unique_names) >= UNDERSPECIFIED_EARLY_STOP_MIN_EXACT_ABV_BEERS:
            qualifying.extend(group)

    qualifying.sort(key=lambda item: item.get("score", 0), reverse=True)
    return qualifying



def _brewery_identity_matches_apparent_beer(brewery, expected_beer):
    """Conservatively recognize when apparent beer text is a brewery identity.

    Multi-word inputs keep the existing leading-prefix rule (for example
    ``Twin Elephant`` -> ``Twin Elephant Brewing Company``). A single-token
    input is much easier to match accidentally, so it is accepted only when
    the normalized brewery name is exactly the same token (for example
    ``Heineken`` -> ``Heineken``).
    """
    expected_norm = normalize(expected_beer)
    brewery_norm = normalize(brewery)
    if not expected_norm or not brewery_norm:
        return False

    expected_words = expected_norm.split()
    if len(expected_words) == 1:
        return brewery_norm == expected_norm

    brewery_words = brewery_norm.split()
    return brewery_words[: len(expected_words)] == expected_words


def _is_brewery_like_input(candidates, expected_beer, expected_brewery):
    """Return True when the apparent beer text is really a brewery identity."""
    if expected_brewery or not expected_beer:
        return False

    for candidate in candidates or []:
        if _brewery_identity_matches_apparent_beer(
            candidate.get("brewery") or "", expected_beer
        ):
            return True

    return False


def _is_brewery_like_initial_page(initial_algolia_page, expected_beer, expected_brewery):
    """Return True when captured page-0 hits show the input is a brewery prefix.

    This is a routing aid only. It deliberately uses the already validated
    page-0 raw hits captured from the exact search query, rather than relying
    solely on the DOM candidate list, whose filtering can hide this structural
    clue.
    """
    if expected_brewery or not expected_beer or not initial_algolia_page:
        return False

    for hit in initial_algolia_page.get("hits") or []:
        brewery = (hit.get("brewery_name") or hit.get("brewery") or "").strip()
        if _brewery_identity_matches_apparent_beer(brewery, expected_beer):
            return True

    return False






def _abv_sorted_strategy(expected_abv):
    """Return the conservative edge-of-range ABV sort strategy, if any."""
    if expected_abv is None:
        return None
    try:
        target = float(expected_abv)
    except Exception:
        return None
    if target >= ABV_DESCENDING_SCAN_MIN:
        return {
            "index": ABV_DESC_ALGOLIA_INDEX,
            "direction": "descending",
            "label": "Highest ABV",
            "threshold_reason": f"target >= {ABV_DESCENDING_SCAN_MIN:g}% high-ABV threshold",
        }
    return None


def scan_abv_sorted_ambiguity(
    page, request_event, search_query, expected_beer, expected_abv, min_score,
    strategy, max_pages=MAX_ALGOLIA_EXPANSION_PAGES,
):
    """Use an Untappd ABV replica to prove broad-input ambiguity only."""
    index_name = strategy["index"]
    direction = strategy["direction"]
    ascending = direction == "ascending"
    diagnostics = {
        "attempted": True, "mode": "abv_sorted_ambiguity",
        "index": index_name, "direction": direction,
        "sort_label": strategy.get("label"),
        "threshold_reason": strategy.get("threshold_reason"),
        "pages_requested": 0, "pages_succeeded": 0, "raw_hits": 0,
        "nbHits": None, "nbPages": None, "page_limit": max_pages,
        "crossed_below_target": False, "crossed_above_target": False,
        "target_band_exhausted": False, "target_abv": expected_abv,
        "exact_abv_candidates": 0, "ambiguity_established": False,
        "stopped_after_page": None, "capped": False, "errors": [],
    }
    expected_words = normalize(expected_beer).split()
    seen = set()
    exact_candidates = []
    previous_numeric_abv = None
    for page_number in range(max_pages or 0):
        _note_algolia_request(expansion=True)
        diagnostics["pages_requested"] += 1
        payload, err = _fetch_algolia_sorted_page(
            page, request_event, search_query, page_number, index_name
        )
        if err:
            diagnostics["errors"].append(f"page {page_number}: {err}")
            break
        results = payload.get("results") or []
        if not results:
            diagnostics["errors"].append(f"page {page_number}: no results payload")
            break
        result = results[0]
        if result.get("index") not in (None, index_name):
            diagnostics["errors"].append(
                f"page {page_number}: unexpected index {result.get('index')!r}"
            )
            break
        diagnostics["pages_succeeded"] += 1
        _ALGOLIA_DEBUG_STATS["beer_expansion_pages_succeeded"] += 1
        if diagnostics["nbHits"] is None:
            diagnostics["nbHits"] = result.get("nbHits")
        if diagnostics["nbPages"] is None:
            diagnostics["nbPages"] = result.get("nbPages")
        hits = result.get("hits") or []
        diagnostics["raw_hits"] += len(hits)
        _ALGOLIA_DEBUG_STATS["beer_expansion_raw_hits"] += len(hits)
        crossed = False
        for hit in hits:
            candidate = _algolia_hit_to_candidate(hit)
            if not candidate:
                continue
            abv = candidate.get("abv")
            if abv is None:
                continue
            if previous_numeric_abv is not None:
                if ascending and abv < previous_numeric_abv - EXACT_ABV_EPSILON:
                    diagnostics["errors"].append("ABV-ascending order validation failed")
                    return [], diagnostics
                if (not ascending) and abv > previous_numeric_abv + EXACT_ABV_EPSILON:
                    diagnostics["errors"].append("ABV-descending order validation failed")
                    return [], diagnostics
            previous_numeric_abv = abv
            if ascending and abv > float(expected_abv) + EXACT_ABV_EPSILON:
                crossed = True
                diagnostics["crossed_above_target"] = True
                diagnostics["target_band_exhausted"] = True
                break
            if (not ascending) and abv < float(expected_abv) - EXACT_ABV_EPSILON:
                crossed = True
                diagnostics["crossed_below_target"] = True
                diagnostics["target_band_exhausted"] = True
                break
            if abs(abv - float(expected_abv)) > EXACT_ABV_EPSILON:
                continue
            if not _brewery_identity_matches_apparent_beer(
                candidate.get("brewery") or "", expected_beer
            ):
                continue
            candidate["score"] = score_candidate(
                search_query, candidate["name"], candidate["text"],
                expected_beer=expected_beer, expected_brewery=None,
                expected_abv=expected_abv,
            )
            if candidate.get("score", 0) < min_score:
                continue
            key = (normalize(candidate.get("name") or ""),
                   normalize(candidate.get("brewery") or ""), candidate.get("bid"))
            if key not in seen:
                seen.add(key)
                exact_candidates.append(candidate)
        diagnostics["exact_abv_candidates"] = len(exact_candidates)
        diagnostics["stopped_after_page"] = page_number
        if crossed:
            break
        nb_pages = diagnostics.get("nbPages")
        if isinstance(nb_pages, int) and page_number + 1 >= nb_pages:
            diagnostics["target_band_exhausted"] = True
            break
    nb_pages = diagnostics.get("nbPages")
    if (max_pages is not None and isinstance(nb_pages, int) and nb_pages > max_pages
            and diagnostics["pages_succeeded"] >= max_pages
            and not diagnostics["target_band_exhausted"]):
        diagnostics["capped"] = True
        _ALGOLIA_DEBUG_STATS["beer_expansion_capped"] = True
    exact_candidates.sort(key=lambda item: item.get("score", 0), reverse=True)
    diagnostics["ambiguity_established"] = bool(
        diagnostics["target_band_exhausted"] and len(exact_candidates) >= 2
        and not diagnostics["errors"]
    )
    return exact_candidates, diagnostics

def expand_algolia_candidates(
    page,
    request_event,
    query,
    expected_beer=None,
    expected_brewery=None,
    expected_abv=None,
    max_pages=MAX_ALGOLIA_EXPANSION_PAGES,
    initial_page=None,
    min_score=DEFAULT_MIN_SCORE,
):
    """
    Fetch the Algolia result pages for difficult searches and re-score them
    with the same candidate scoring used for the normal DOM path.

    v34 can reuse a validated primary page-0 response. That page counts toward
    max_pages but does not count as another network request.
    """
    parsed_requests = request_event.get("algolia_requests") or []
    if not parsed_requests:
        return [], {
            "attempted": False,
            "pages_requested": 0,
            "pages_succeeded": 0,
            "pages_reused": 0,
            "reused_hits": 0,
            "raw_hits": 0,
            "raw_hits_scored": 0,
            "unique_candidates": 0,
            "page_limit": max_pages,
            "capped": False,
            "errors": ["no parsed Algolia request available"],
        }

    candidates = []
    seen = set()
    pages_requested = 0
    pages_succeeded = 0
    pages_reused = 0
    reused_hits = 0
    raw_hits = 0
    raw_hits_scored = 0
    nb_hits = None
    nb_pages = None
    errors = []
    ambiguity_early_stopped = False
    ambiguity_early_stop_candidates = []
    ambiguity_early_stop_after_page = None

    def _consume_hits(hits):
        nonlocal raw_hits_scored
        raw_hits_scored += len(hits)

        for hit in hits:
            candidate = _algolia_hit_to_candidate(hit)
            if not candidate:
                continue

            key = (
                normalize(candidate.get("name") or ""),
                normalize(candidate.get("brewery") or ""),
                candidate.get("bid"),
            )

            if key in seen:
                continue
            seen.add(key)

            candidate["score"] = score_candidate(
                query,
                candidate["name"],
                candidate["text"],
                expected_beer=expected_beer,
                expected_brewery=expected_brewery,
                expected_abv=expected_abv,
            )

            candidates.append(candidate)

    # Reuse page 0 only when the caller supplied a fully validated matching
    # response. Correctness never depends on reuse: without it, page 0 is
    # fetched exactly as in v33.
    reuse_initial_page = bool(
        initial_page
        and initial_page.get("page") == 0
        and isinstance(initial_page.get("hits"), list)
        and isinstance(initial_page.get("nbHits"), int)
        and isinstance(initial_page.get("nbPages"), int)
    )

    page_number = 0
    if reuse_initial_page and (max_pages is None or max_pages > 0):
        hits = initial_page.get("hits") or []
        nb_hits = initial_page.get("nbHits")
        nb_pages = initial_page.get("nbPages")
        pages_reused = 1
        reused_hits = len(hits)
        _ALGOLIA_DEBUG_STATS["beer_expansion_reused_pages"] += 1
        _ALGOLIA_DEBUG_STATS["beer_expansion_reused_hits"] += len(hits)
        _consume_hits(hits)
        ambiguity_early_stop_candidates = _underspecified_brewery_ambiguity_candidates(
            candidates, expected_beer, expected_brewery, expected_abv, min_score
        )
        if ambiguity_early_stop_candidates:
            ambiguity_early_stopped = True
            ambiguity_early_stop_after_page = 0
        page_number = 1

    while not ambiguity_early_stopped:
        if max_pages is not None and page_number >= max_pages:
            break
        if nb_pages is not None and page_number >= nb_pages:
            break

        _note_algolia_request(expansion=True)
        payload, err = _fetch_algolia_page(
            page,
            request_event,
            page_number=page_number,
        )
        pages_requested += 1

        if err:
            errors.append(f"page {page_number}: {err}")
            break

        pages_succeeded += 1
        _ALGOLIA_DEBUG_STATS["beer_expansion_pages_succeeded"] += 1

        results = payload.get("results") or []
        if not results:
            break

        result = results[0]
        if nb_hits is None:
            nb_hits = result.get("nbHits")
        if nb_pages is None:
            nb_pages = result.get("nbPages")

        hits = result.get("hits") or []
        raw_hits += len(hits)
        _ALGOLIA_DEBUG_STATS["beer_expansion_raw_hits"] += len(hits)
        _consume_hits(hits)

        ambiguity_early_stop_candidates = _underspecified_brewery_ambiguity_candidates(
            candidates, expected_beer, expected_brewery, expected_abv, min_score
        )
        if ambiguity_early_stop_candidates:
            ambiguity_early_stopped = True
            ambiguity_early_stop_after_page = page_number

        page_number += 1

    logical_pages_examined = pages_reused + pages_succeeded
    capped = bool(
        max_pages is not None
        and nb_pages is not None
        and nb_pages > max_pages
        and logical_pages_examined >= max_pages
    )
    if capped:
        _ALGOLIA_DEBUG_STATS["beer_expansion_capped"] = True

    candidates.sort(
        key=lambda item: item.get("score", 0),
        reverse=True,
    )

    return candidates, {
        "attempted": True,
        "pages_requested": pages_requested,
        "pages_succeeded": pages_succeeded,
        "pages_reused": pages_reused,
        "reused_hits": reused_hits,
        "raw_hits": raw_hits,
        "raw_hits_scored": raw_hits_scored,
        "unique_candidates": len(candidates),
        "nbHits": nb_hits,
        "nbPages": nb_pages,
        "page_limit": max_pages,
        "capped": capped,
        "ambiguity_early_stopped": ambiguity_early_stopped,
        "ambiguity_early_stop_after_page": ambiguity_early_stop_after_page,
        "ambiguity_early_stop_candidate_count": len(ambiguity_early_stop_candidates),
        "errors": errors,
    }


def same_abv_family_variants(
    candidates,
    expected_beer,
    expected_abv,
    tolerance=0.05,
):
    """
    Return same-ABV variants belonging to the beer family named by the menu.

    If the parser could not separate brewery from beer (for example
    "Trillium Daily Serving"), discover the longest suffix of the menu text
    that behaves like a beer-family prefix across multiple candidates.
    """
    if expected_abv is None or not expected_beer:
        return []

    expected_norm = normalize(expected_beer)
    expected_words = expected_norm.split()

    if len(expected_words) < FAMILY_MIN_WORDS:
        return []

    candidate_rows = []
    for candidate in candidates:
        name = (candidate.get("name") or "").strip()
        if not name:
            continue

        abv = candidate.get("abv")
        if abv is None:
            continue

        try:
            if abs(float(abv) - float(expected_abv)) > tolerance:
                continue
        except Exception:
            continue

        candidate_rows.append(
            (candidate, normalize(name))
        )

    if not candidate_rows:
        return []

    # First try the parsed beer text exactly. If that fails because the parser
    # included a brewery token (e.g. "Trillium Daily Serving"), progressively
    # remove leading words and choose the longest suffix that prefixes at least
    # two same-ABV candidate names.
    family_norm = None

    for start_idx in range(
        0,
        max(1, len(expected_words) - FAMILY_MIN_WORDS + 1),
    ):
        target_words = expected_words[start_idx:]

        if len(target_words) < FAMILY_MIN_WORDS:
            continue

        target = " ".join(target_words)

        matching_count = sum(
            1
            for _, candidate_norm in candidate_rows
            if (
                candidate_norm == target
                or candidate_norm.startswith(target + " ")
            )
        )

        if matching_count >= 2:
            family_norm = target
            break

    if not family_norm:
        return []

    matches = []
    seen_names = set()

    for candidate, candidate_norm in candidate_rows:
        if not (
            candidate_norm == family_norm
            or candidate_norm.startswith(family_norm + " ")
        ):
            continue

        name_key = candidate_norm
        if name_key in seen_names:
            continue

        seen_names.add(name_key)
        matches.append(candidate)

    matches.sort(
        key=lambda item: (
            -(item.get("score") or 0),
            normalize(item.get("name") or ""),
        )
    )

    return matches








def release_family_candidates(candidates, expected_beer):
    """
    Return candidates that are strict members of the menu beer's release family.
    """
    if not expected_beer:
        return []

    expected_norm = normalize(expected_beer)
    if not expected_norm:
        return []

    return [
        candidate
        for candidate in candidates
        if (
            normalize(candidate.get("name") or "") == expected_norm
            or normalize(candidate.get("name") or "").startswith(
                expected_norm + " "
            )
        )
    ]


def apply_exact_abv_family_preference(
    candidates,
    expected_beer,
    expected_abv,
):
    """
    Prefer one uniquely exact-ABV sibling over merely-close siblings.

    This is intentionally a post-expansion family disambiguation rule rather
    than a change to global ABV verification.
    """
    if expected_abv is None or len(candidates) < 2:
        return candidates, None

    family = release_family_candidates(
        candidates,
        expected_beer,
    )

    if len(family) < 2:
        return candidates, None

    exact = [
        candidate
        for candidate in family
        if candidate.get("abv") is not None
        and abs(candidate["abv"] - expected_abv) <= EXACT_ABV_EPSILON
    ]

    if len(exact) != 1:
        return candidates, None

    winner = exact[0]
    winner["score"] = min(
        1.0,
        winner.get("score", 0) + EXACT_ABV_FAMILY_BONUS,
    )

    candidates.sort(
        key=lambda item: item.get("score", 0),
        reverse=True,
    )

    return candidates, winner




def same_abv_family_discovery_trigger(candidates, expected_beer, expected_abv):
    """
    Return True when the loaded result set already shows that the menu text is
    an unqualified beer-family prefix, but only one currently loaded family
    member has the exact menu ABV.

    That situation is not enough to confirm the exact-ABV member: later
    Algolia pages may contain additional exact-ABV siblings (Daily Serving is
    the motivating case). This is only an expansion trigger; it never changes
    scores or establishes ambiguity by itself.
    """
    if expected_abv is None or not expected_beer or len(candidates) < 2:
        return False

    expected_words = normalize(expected_beer).split()
    if len(expected_words) < FAMILY_MIN_WORDS:
        return False

    for size in range(len(expected_words), FAMILY_MIN_WORDS - 1, -1):
        for start in range(0, len(expected_words) - size + 1):
            phrase = " ".join(expected_words[start:start + size])
            family_matches = []

            for candidate in candidates:
                candidate_norm = normalize(candidate.get("name") or "")
                if candidate_norm.startswith(phrase + " "):
                    family_matches.append(candidate)

            if len(family_matches) < 2:
                continue

            exact_matches = [
                candidate for candidate in family_matches
                if candidate.get("abv") is not None
                and abs(float(candidate["abv"]) - float(expected_abv))
                    <= EXACT_ABV_EPSILON
            ]

            if len(exact_matches) == 1:
                return True

    return False

def detect_candidate_ambiguity(
    candidates,
    expected_beer=None,
    expected_abv=None,
):
    """
    Return a human-readable reason when the menu evidence does not identify
    one beer uniquely.

    Two cases are handled:
      1. The top two plausible candidates are effectively tied.
      2. The menu names only a beer family/series (e.g. "Daily Serving"),
         while multiple Untappd variants extend that same family name.
    """
    if len(candidates) < 2:
        return None

    best = candidates[0]
    second = candidates[1]

    # Near-tie: the ranking itself cannot separate two plausible matches.
    if (
        best["score"] >= DEFAULT_MIN_SCORE
        and second["score"] >= DEFAULT_MIN_SCORE
        and (best["score"] - second["score"]) <= AMBIGUITY_SCORE_MARGIN
    ):
        return (
            f"Top candidates are too close: "
            f"'{best['name']}' ({best['score']:.3f}) vs "
            f"'{second['name']}' ({second['score']:.3f})"
        )

    if not expected_beer:
        return None

    expected_words = normalize(expected_beer).split()

    # Look for a multi-word phrase from the menu that appears at the start
    # of several candidate beer names, while each candidate adds extra
    # variant words. This is a strong signal that the menu supplied a
    # family/series name but not the exact variant.
    for size in range(len(expected_words), FAMILY_MIN_WORDS - 1, -1):
        for start in range(0, len(expected_words) - size + 1):
            phrase_words = expected_words[start:start + size]
            phrase = " ".join(phrase_words)

            family_matches = []

            for candidate in candidates:
                candidate_norm = normalize(candidate["name"])

                if candidate_norm == phrase:
                    # Exact beer-name match: not a family ambiguity.
                    continue

                if candidate_norm.startswith(phrase + " "):
                    family_matches.append(candidate)

            if len(family_matches) >= 2:
                if expected_abv is not None:
                    exact_family_matches = [
                        item
                        for item in family_matches
                        if item.get("abv") is not None
                        and abs(
                            item["abv"] - expected_abv
                        ) <= EXACT_ABV_EPSILON
                    ]

                    if len(exact_family_matches) == 1:
                        continue

                names = ", ".join(
                    f"'{item['name']}'"
                    for item in family_matches[:3]
                )

                return (
                    f"Multiple candidates include {names}"
                )

    return None


# ============================================================
# Beer detail parsing
# ============================================================





RELEASE_YEAR_RE = re.compile(
    r"\b(?:19|20)\d{2}\b"
)


def candidate_adds_release_qualifier(expected_beer, candidate_name):
    """
    Return True when an unqualified menu beer name appears to match a
    year-qualified Untappd release.

    This is intentionally conservative:
      - the menu name itself must not already contain a year;
      - the candidate must contain a four-digit release year;
      - after normalization, the candidate must be the menu beer name plus
        additional trailing qualifier text.

    Examples:
        Arabesque -> Arabesque (2023)          True
        KBS Iced Mocha -> KBS Iced Mocha 2026  True
        Arabesque (2025) -> Arabesque (2025)   False
        Executioner -> Baby Executioner 2026   False
    """
    if not expected_beer or not candidate_name:
        return False

    if RELEASE_YEAR_RE.search(expected_beer):
        return False

    if not RELEASE_YEAR_RE.search(candidate_name):
        return False

    expected_norm = normalize(expected_beer)
    candidate_norm = normalize(candidate_name)

    if not expected_norm or not candidate_norm:
        return False

    return candidate_norm.startswith(expected_norm + " ")


GENERIC_BREWERY_SEARCH_SUFFIX_RE = re.compile(
    r"""
    (?:
        \s+
        (?:
            co(?:mpany)?
            |inc(?:orporated)?
            |llc
            |ltd
            |limited
            |corp(?:oration)?
            |plc
        )
        \.?
    )+
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def normalize_brewery_for_search(brewery):
    """
    Return a search-oriented brewery form while preserving the original
    brewery string elsewhere for verification.

    Only trailing generic legal/company suffixes are removed. Core brewery
    words such as "Brewing" and "Brewery" are intentionally retained because
    they can improve Untappd search precision.
    """
    if not brewery:
        return None

    cleaned = final_query_cleanup(brewery)
    cleaned = GENERIC_BREWERY_SEARCH_SUFFIX_RE.sub("", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)

    return cleaned or None


def collaboration_brewery_components_for_search(brewery):
    """Return the two brewery components from an explicit ``A x B`` collaboration."""
    normalized_brewery = normalize_brewery_for_search(brewery)
    if not normalized_brewery:
        return []

    parts = COLLABORATION_SEPARATOR_RE.split(normalized_brewery, maxsplit=1)
    if len(parts) != 2:
        return []

    cleaned = [final_query_cleanup(part) for part in parts]
    return [part for part in cleaned if part]


def primary_brewery_component_for_search(brewery):
    """Backward-compatible helper returning the first explicit collaborator."""
    parts = collaboration_brewery_components_for_search(brewery)
    return parts[0] if parts else None


def strip_redundant_terminal_style_for_search(expected_beer, expected_style):
    """
    Remove a terminal style phrase only when that exact style was supplied
    separately by the parser. This is a search-recall adapter, not a change to
    the stored beer identity.

    Examples:
      beer="Élixir-IPA", style="IPA" -> "Élixir"
      beer="Foo West Coast IPA", style="West Coast IPA" -> "Foo"

    A partial style match is intentionally not removed.
    """
    beer = (expected_beer or "").strip()
    style = (expected_style or "").strip()
    if not beer or not style:
        return None

    # Require the complete normalized style phrase at the end of the beer
    # name, allowing only ordinary menu punctuation between base name/style.
    beer_norm = normalize(beer)
    style_norm = normalize(style)
    if not beer_norm or not style_norm:
        return None
    if beer_norm == style_norm or not beer_norm.endswith(" " + style_norm):
        return None

    style_pattern = r"\s+".join(
        re.escape(part) for part in re.split(r"\s+", style.strip()) if part
    )
    match = re.search(
        rf"(?:\s*[-–—/:|]\s*|\s+){style_pattern}\s*$",
        beer,
        re.IGNORECASE,
    )
    if not match:
        return None

    stripped = final_query_cleanup(beer[:match.start()])
    return stripped if stripped and normalize(stripped) != beer_norm else None


def _meaningful_brewery_words(text):
    return {
        word
        for word in normalize(text or "").split()
        if len(word) >= 3
        and word not in {
            "brew", "brewing", "brewery", "company",
            "co", "inc", "llc", "ltd", "limited",
            "corp", "corporation", "plc",
        }
    }


def candidate_has_brewery_overlap(candidate, expected_brewery):
    """Return True when a candidate brewery shares meaningful menu brewery evidence."""
    if not expected_brewery:
        return True

    candidate_brewery = candidate.get("brewery") or extract_brewery_from_result(
        candidate.get("text", ""),
        candidate.get("name", ""),
    )
    if not candidate_brewery:
        # Unknown is not treated as an explicit contradiction.
        return True

    expected_words = _meaningful_brewery_words(expected_brewery)
    candidate_words = _meaningful_brewery_words(candidate_brewery)
    if not expected_words or not candidate_words:
        return True

    return bool(expected_words & candidate_words)


MAX_TRAILING_BEER_RELAX_TOKENS = 2
MIN_TRAILING_RELAX_BASE_TOKENS = 2


def trailing_beer_relaxations_for_search(expected_beer):
    """Return bounded base-name relaxations by trimming 1-2 trailing tokens."""
    beer = final_query_cleanup(expected_beer or "")
    if not beer:
        return []

    raw_tokens = beer.split()
    relaxations = []
    seen = {normalize(beer)}

    for remove_count in range(1, MAX_TRAILING_BEER_RELAX_TOKENS + 1):
        if len(raw_tokens) <= remove_count:
            break
        candidate = final_query_cleanup(" ".join(raw_tokens[:-remove_count]))
        candidate_norm = normalize(candidate)
        if (
            not candidate_norm
            or candidate_norm in seen
            or len(candidate_norm.split()) < MIN_TRAILING_RELAX_BASE_TOKENS
        ):
            continue
        seen.add(candidate_norm)
        relaxations.append(candidate)

    return relaxations


def candidate_matches_trailing_relaxed_identity(candidate, expected_beer):
    """Require the returned Untappd beer name to be the menu beer's base prefix."""
    expected_norm = normalize(expected_beer or "")
    candidate_norm = normalize(candidate.get("name") or "")
    if not expected_norm or not candidate_norm:
        return False
    return expected_norm == candidate_norm or expected_norm.startswith(candidate_norm + " ")


def trailing_relaxation_search_queries(expected_beer, expected_brewery):
    """Build brewery-qualified search strings for bounded trailing relaxation."""
    if not expected_beer or not expected_brewery:
        return []
    normalized_brewery = normalize_brewery_for_search(expected_brewery)
    if not normalized_brewery:
        return []
    brewery_for_query = collaboration_brewery_for_search(normalized_brewery)
    return [
        final_query_cleanup(f"{brewery_for_query} {base}")
        for base in trailing_beer_relaxations_for_search(expected_beer)
    ]


def build_search_fallback_queries(
    original_query,
    expected_beer=None,
    expected_brewery=None,
    expected_style=None,
    enable_trailing_relaxation=False,
):
    """
    Build conservative fallbacks whose token content actually changes.

    A redundant terminal style phrase may first be removed when it exactly
    matches separately parsed style metadata. Collaboration fallbacks then
    reduce brewery evidence to A, then B, then beer-only as before.
    """
    if not expected_beer:
        return []

    fallback_queries = []
    seen = {normalize(original_query)}

    collaborators = collaboration_brewery_components_for_search(expected_brewery)
    normalized_brewery = normalize_brewery_for_search(expected_brewery)

    stripped_beer = strip_redundant_terminal_style_for_search(
        expected_beer, expected_style
    )
    if stripped_beer:
        if collaborators:
            full_collaboration = collaboration_brewery_for_search(
                normalized_brewery or expected_brewery
            )
            combined = final_query_cleanup(f"{full_collaboration} {stripped_beer}")
        elif normalized_brewery:
            combined = final_query_cleanup(f"{normalized_brewery} {stripped_beer}")
        else:
            combined = final_query_cleanup(stripped_beer)
        key = normalize(combined)
        if key and key not in seen:
            seen.add(key)
            fallback_queries.append(combined)

    # v47: only a true zero-hit primary search may trigger generic trailing
    # token relaxation. A merely weak/nonzero search is not enough evidence
    # that the menu contains extra descriptive suffix text.
    if enable_trailing_relaxation:
        for relaxed_query in trailing_relaxation_search_queries(
            expected_beer, expected_brewery
        ):
            key = normalize(relaxed_query)
            if key and key not in seen:
                seen.add(key)
                fallback_queries.append(relaxed_query)

    if collaborators:
        brewery_forms = collaborators
    else:
        brewery_forms = [normalized_brewery] if normalized_brewery else []

    for brewery_form in brewery_forms:
        combined = final_query_cleanup(f"{expected_beer} {brewery_form}")
        key = normalize(combined)
        if key and key not in seen:
            seen.add(key)
            fallback_queries.append(combined)

    beer_only = final_query_cleanup(expected_beer)
    key = normalize(beer_only)
    if key and key not in seen:
        fallback_queries.append(beer_only)

    return fallback_queries


def _is_rate_limit_error_message(message):
    """Return True when a diagnostic error clearly represents HTTP 429."""
    return bool(
        message
        and re.search(r"\bHTTP\s+429\b", str(message), re.IGNORECASE)
    )


def _expansion_was_rate_limited(diagnostics):
    if not diagnostics:
        return False

    return any(
        _is_rate_limit_error_message(error)
        for error in (diagnostics.get("errors") or [])
    )








def _brewery_from_algolia_initial_page(initial_page, candidate):
    """Recover brewery metadata for a DOM candidate from captured Algolia page 0.

    This is a presentation/data-preservation helper only. It does not change
    candidate scoring or identity decisions. Prefer an exact Untappd beer id
    match when available; otherwise require an exact normalized beer-name match.
    """
    if not initial_page or not candidate:
        return None

    hits = initial_page.get("hits") or []
    candidate_url = candidate.get("url") or candidate.get("href") or ""
    candidate_name = normalize(candidate.get("name") or "")

    candidate_bid = None
    bid_match = re.search(r"/(\d+)(?:[/?#]|$)", candidate_url)
    if bid_match:
        candidate_bid = bid_match.group(1)

    if candidate_bid:
        for hit in hits:
            hit_bid = hit.get("bid")
            if hit_bid is not None and str(hit_bid) == candidate_bid:
                brewery = (hit.get("brewery_name") or "").strip()
                if brewery:
                    return brewery

    if candidate_name:
        name_matches = [
            hit
            for hit in hits
            if normalize(hit.get("beer_name") or "") == candidate_name
        ]
        breweries = {
            (hit.get("brewery_name") or "").strip()
            for hit in name_matches
            if (hit.get("brewery_name") or "").strip()
        }
        if len(breweries) == 1:
            return next(iter(breweries))

    return None



def _type_name_from_algolia_initial_page(initial_page, candidate):
    """Recover Untappd's Algolia ``type_name`` without another request.

    Prefer exact beer-id correspondence. Fall back to normalized beer name
    only when that name maps to one unique non-empty type_name on the captured
    page. This is display/output metadata only and never affects matching.
    """
    if not initial_page or not candidate:
        return None

    hits = initial_page.get("hits") or []
    candidate_bid = candidate.get("bid")
    if candidate_bid is None:
        candidate_url = candidate.get("url") or candidate.get("href") or ""
        bid_match = re.search(r"/(\d+)(?:[/?#]|$)", candidate_url)
        if bid_match:
            candidate_bid = bid_match.group(1)

    if candidate_bid is not None:
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            if str(hit.get("bid")) == str(candidate_bid):
                value = (hit.get("type_name") or "").strip()
                return value or None

    candidate_name = normalize(candidate.get("name") or "")
    if not candidate_name:
        return None

    values = {
        (hit.get("type_name") or "").strip()
        for hit in hits
        if isinstance(hit, dict)
        and normalize(hit.get("beer_name") or "") == candidate_name
        and (hit.get("type_name") or "").strip()
    }
    if len(values) == 1:
        return next(iter(values))
    return None

# ============================================================
# Optional v66 matcher phase timing diagnostics
# ============================================================
# Measurement-only instrumentation. These timings do not affect candidate
# scoring, request strategy, ambiguity handling, or result construction.
class _MatcherTimingStats(TypedDict):
    count: int
    total_seconds: float
    min_seconds: Optional[float]
    max_seconds: Optional[float]
    phase_totals: Dict[str, float]
    phase_counts: Dict[str, int]
    last_total_seconds: Optional[float]
    residual_total_seconds: float


_MATCHER_TIMING_STATS: _MatcherTimingStats = {
    "count": 0,
    "total_seconds": 0.0,
    "min_seconds": None,
    "max_seconds": None,
    "phase_totals": {},
    "phase_counts": {},
    "last_total_seconds": None,
    "residual_total_seconds": 0.0,
}

_CURRENT_MATCHER_PHASE_SECONDS = 0.0


def reset_matcher_timing_stats():
    reset_detail_algolia_parity_stats()
    reset_algolia_confirmation_stats()
    _MATCHER_TIMING_STATS.update({
        "count": 0,
        "total_seconds": 0.0,
        "min_seconds": None,
        "max_seconds": None,
        "phase_totals": {},
        "phase_counts": {},
        "last_total_seconds": None,
        "residual_total_seconds": 0.0,
    })


def get_matcher_timing_stats():
    stats = dict(_MATCHER_TIMING_STATS)
    stats["phase_totals"] = dict(_MATCHER_TIMING_STATS["phase_totals"])
    stats["phase_counts"] = dict(_MATCHER_TIMING_STATS["phase_counts"])
    return stats


def get_last_matcher_timing_seconds():
    return _MATCHER_TIMING_STATS.get("last_total_seconds")


def _record_matcher_phase(label, query, elapsed_seconds):
    global _CURRENT_MATCHER_PHASE_SECONDS
    if not debug_timing_enabled():
        return
    _CURRENT_MATCHER_PHASE_SECONDS += elapsed_seconds
    phase_totals = _MATCHER_TIMING_STATS["phase_totals"]
    phase_counts = _MATCHER_TIMING_STATS["phase_counts"]
    phase_totals[label] = phase_totals.get(label, 0.0) + elapsed_seconds
    phase_counts[label] = phase_counts.get(label, 0) + 1
    print(f"[timing] {label}: {elapsed_seconds:.3f}s | {query}")


def _timed_matcher_call(label, query, func):
    if not debug_timing_enabled():
        return func()
    started = perf_counter()
    try:
        return func()
    finally:
        _record_matcher_phase(label, query, perf_counter() - started)


def _record_matcher_total(query, elapsed_seconds, phase_seconds):
    if not debug_timing_enabled():
        return
    stats = _MATCHER_TIMING_STATS
    stats["count"] += 1
    stats["total_seconds"] += elapsed_seconds
    stats["last_total_seconds"] = elapsed_seconds
    residual = max(0.0, elapsed_seconds - phase_seconds)
    stats["residual_total_seconds"] += residual
    current_min = stats["min_seconds"]
    current_max = stats["max_seconds"]
    stats["min_seconds"] = elapsed_seconds if current_min is None else min(current_min, elapsed_seconds)
    stats["max_seconds"] = elapsed_seconds if current_max is None else max(current_max, elapsed_seconds)
    print(f"[timing] matcher residual / unaccounted: {residual:.3f}s | {query}")
    print(f"[timing] matcher total: {elapsed_seconds:.3f}s | {query}")


def print_matcher_timing_summary():
    if not debug_timing_enabled():
        return
    stats = _MATCHER_TIMING_STATS
    print()
    print("Matcher-phase timing summary")
    print("=" * 70)
    count = stats["count"]
    if not count:
        print("No timed matcher items.")
        return
    total = stats["total_seconds"]
    print(f"Timed matcher items: {count}")
    print(f"Total matcher elapsed time: {total:.3f}s")
    print(f"Average matcher elapsed time: {total / count:.3f}s")
    print(f"Fastest matcher elapsed time: {stats['min_seconds']:.3f}s")
    print(f"Slowest matcher elapsed time: {stats['max_seconds']:.3f}s")
    print("Phase totals:")
    phase_totals = stats["phase_totals"]
    phase_counts = stats["phase_counts"]
    for label, phase_total in phase_totals.items():
        phase_count = phase_counts.get(label, 0)
        average = phase_total / phase_count if phase_count else 0.0
        print(f"  {label}: {phase_total:.3f}s total / {phase_count} = {average:.3f}s avg")
    residual_total = stats["residual_total_seconds"]
    print(f"  matcher residual / unaccounted: {residual_total:.3f}s total / {count} = {residual_total / count:.3f}s avg")




# ============================================================
# v70 confirmed-result authority
# ============================================================
class _AlgoliaConfirmationStats(TypedDict):
    confirmed_from_algolia: int
    detail_page_fallbacks: int


_ALGOLIA_CONFIRMATION_STATS: _AlgoliaConfirmationStats = {
    "confirmed_from_algolia": 0,
    "detail_page_fallbacks": 0,
}


def reset_algolia_confirmation_stats():
    _ALGOLIA_CONFIRMATION_STATS.update({
        "confirmed_from_algolia": 0,
        "detail_page_fallbacks": 0,
    })


def get_algolia_confirmation_stats():
    return dict(_ALGOLIA_CONFIRMATION_STATS)


def _record_algolia_confirmation(detail_fallback: bool):
    if detail_fallback:
        _ALGOLIA_CONFIRMATION_STATS["detail_page_fallbacks"] += 1
    else:
        _ALGOLIA_CONFIRMATION_STATS["confirmed_from_algolia"] += 1


def _confirmed_info_from_algolia(candidate, brewery):
    """Build a confirmed result without detail navigation when core fields exist."""
    name = (candidate.get("name") or "").strip()
    rating = _as_float(candidate.get("rating_score"))
    ratings = _as_int(candidate.get("rating_count"))
    abv = _as_float(candidate.get("abv"))
    url = candidate.get("url")
    if not name or rating is None or ratings is None or abv is None or not url:
        return None
    ibu = candidate.get("ibu")
    if ibu in (None, ""):
        ibu = None
    else:
        try:
            ibu = f"{float(ibu):g}"
        except (TypeError, ValueError):
            ibu = None
    return {
        "beer": name,
        "brewery": brewery or "Unknown",
        "rating": rating,
        "ratings": ratings,
        "abv": f"{abv:g}%",
        "ibu": ibu,
        "url": url,
    }


def print_algolia_confirmation_summary():
    if not debug_timing_enabled():
        return
    stats = _ALGOLIA_CONFIRMATION_STATS
    print()
    print("Confirmed-result source summary")
    print("=" * 70)
    print(f"Confirmed from Algolia: {stats['confirmed_from_algolia']}")
    print(f"Detail-page fallbacks: {stats['detail_page_fallbacks']}")


# ============================================================
# Retained v69 detail-page / Algolia field parity diagnostics
# ============================================================
# Shadow-only diagnostics. Detail-page extraction remains authoritative in
# v69; these counters only compare independently available fields from the
# confirmed detail page against the already captured Algolia candidate.
class _DetailAlgoliaParityStats(TypedDict):
    compared: int
    exact: int
    field_mismatches: Dict[str, int]
    algolia_missing: Dict[str, int]
    detail_missing: Dict[str, int]


_DETAIL_ALGOLIA_PARITY_STATS: _DetailAlgoliaParityStats = {
    "compared": 0,
    "exact": 0,
    "field_mismatches": {},
    "algolia_missing": {},
    "detail_missing": {},
}


def reset_detail_algolia_parity_stats():
    _DETAIL_ALGOLIA_PARITY_STATS.update({
        "compared": 0,
        "exact": 0,
        "field_mismatches": {},
        "algolia_missing": {},
        "detail_missing": {},
    })


def get_detail_algolia_parity_stats():
    stats = dict(_DETAIL_ALGOLIA_PARITY_STATS)
    stats["field_mismatches"] = dict(_DETAIL_ALGOLIA_PARITY_STATS["field_mismatches"])
    stats["algolia_missing"] = dict(_DETAIL_ALGOLIA_PARITY_STATS["algolia_missing"])
    stats["detail_missing"] = dict(_DETAIL_ALGOLIA_PARITY_STATS["detail_missing"])
    return stats


def _as_float(value):
    if value in (None, ""):
        return None
    try:
        if isinstance(value, str):
            value = value.strip().rstrip("%")
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value):
    if value in (None, ""):
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", "").strip()
        return int(value)
    except (TypeError, ValueError):
        return None


def _detail_algolia_field_comparison(detail_info, candidate):
    """Return independent detail-vs-Algolia field comparisons for v69.

    Brewery and type_name are intentionally not included: current detail-page
    extraction does not independently parse those fields, so comparing them
    would merely compare Algolia-derived metadata with itself.
    """
    values = {
        "name": (
            detail_info.get("beer"),
            candidate.get("name"),
        ),
        "rating": (
            _as_float(detail_info.get("rating")),
            _as_float(candidate.get("rating_score")),
        ),
        "ratings": (
            _as_int(detail_info.get("ratings")),
            _as_int(candidate.get("rating_count")),
        ),
        "abv": (
            _as_float(detail_info.get("abv")),
            _as_float(candidate.get("abv")),
        ),
    }
    result = {}
    for field, (detail_value, algolia_value) in values.items():
        if detail_value is None and algolia_value is None:
            state = "both-missing"
            equal = True
        elif detail_value is None:
            state = "detail-missing"
            equal = False
        elif algolia_value is None:
            state = "algolia-missing"
            equal = False
        elif field == "name":
            equal = normalize(str(detail_value)) == normalize(str(algolia_value))
            state = "equal" if equal else "mismatch"
        elif field in {"rating", "abv"}:
            equal = abs(float(detail_value) - float(algolia_value)) <= 0.0005
            state = "equal" if equal else "mismatch"
        else:
            equal = detail_value == algolia_value
            state = "equal" if equal else "mismatch"
        result[field] = {
            "detail": detail_value,
            "algolia": algolia_value,
            "equal": equal,
            "state": state,
        }
    return result


def _record_detail_algolia_parity(query, detail_info, candidate):
    if not debug_timing_enabled():
        return
    comparison = _detail_algolia_field_comparison(detail_info, candidate)
    stats = _DETAIL_ALGOLIA_PARITY_STATS
    stats["compared"] += 1
    differing = []
    for field, item in comparison.items():
        state = item["state"]
        if state == "equal" or state == "both-missing":
            continue
        differing.append(field)
        if state == "algolia-missing":
            bucket = stats["algolia_missing"]
        elif state == "detail-missing":
            bucket = stats["detail_missing"]
        else:
            bucket = stats["field_mismatches"]
        bucket[field] = bucket.get(field, 0) + 1

    if not differing:
        stats["exact"] += 1
        print(f"[detail-parity] PARITY: name/rating/ratings/abv | {query}")
        return

    print(f"[detail-parity] DIFF: {','.join(differing)} | {query}")
    for field in differing:
        item = comparison[field]
        print(
            f"[detail-parity]   {field}: "
            f"detail={item['detail']!r} | Algolia={item['algolia']!r} "
            f"| state={item['state']}"
        )


def print_detail_algolia_parity_summary():
    if not debug_timing_enabled():
        return
    stats = _DETAIL_ALGOLIA_PARITY_STATS
    print()
    print("Detail-page / Algolia field parity summary")
    print("=" * 70)
    compared = stats["compared"]
    if not compared:
        print("No confirmed detail pages were compared with Algolia candidates.")
        return
    print(f"Confirmed detail pages compared: {compared}")
    print(f"Exact comparable-field parity: {stats['exact']}/{compared}")
    for label, key in (
        ("Value mismatches", "field_mismatches"),
        ("Algolia missing fields", "algolia_missing"),
        ("Detail-page missing fields", "detail_missing"),
    ):
        bucket = stats[key]
        if bucket:
            rendered = ", ".join(f"{field}={count}" for field, count in sorted(bucket.items()))
        else:
            rendered = "none"
        print(f"{label}: {rendered}")
    print("Compared independently: beer name, rating, ratings count, ABV.")
    print("Not independently compared: brewery and type_name (detail extraction currently receives/recovers those from search metadata).")
    print("Detail-page values remained authoritative in v69; v70 uses Algolia when complete.")

# ============================================================
# v68 captured-Algolia page-0 candidate construction
# ============================================================
# Candidate construction uses only the already captured page-0 payload.
# It issues no additional requests and preserves native Algolia ABV precision.

def _candidate_identity(candidate):
    url = (candidate.get("url") or candidate.get("href") or "").strip()
    if url:
        return ("url", url.rstrip("/"))
    return (
        "fields",
        normalize(candidate.get("name") or ""),
        normalize(candidate.get("brewery") or ""),
        candidate.get("abv"),
    )


def _algolia_page0_candidates(
    initial_algolia_page,
    query,
    expected_beer=None,
    expected_brewery=None,
    expected_abv=None,
):
    """Build the authoritative page-0 candidate pool from captured Algolia hits."""
    if not initial_algolia_page:
        return []

    query_words = {word for word in normalize(query).split() if len(word) >= 3}
    required = max(1, (len(query_words) + 1) // 2)
    candidates = []
    seen = set()

    for hit in initial_algolia_page.get("hits") or []:
        candidate = _algolia_hit_to_candidate(hit)
        if not candidate:
            continue
        identity = _candidate_identity(candidate)
        if identity in seen:
            continue
        seen.add(identity)

        block_norm = normalize(candidate.get("text") or "")
        matches = sum(1 for word in query_words if word in block_norm)
        if matches < required:
            continue

        candidate["score"] = score_candidate(
            query,
            candidate.get("name") or "",
            candidate.get("text") or "",
            expected_beer=expected_beer,
            expected_brewery=expected_brewery,
            expected_abv=expected_abv,
        )
        candidates.append(candidate)

    candidates.sort(key=lambda item: item.get("score") or 0, reverse=True)
    return candidates


def evaluate_and_expand_candidates(
    page,
    search_query,
    candidates,
    algolia_request,
    min_score,
    expected_beer=None,
    expected_brewery=None,
    expected_abv=None,
    initial_nb_hits=None,
    initial_algolia_page=None,
):
    """
    Single source of truth for the "is this candidate set good enough, and
    if not, should we run the slower complete Algolia expansion" decision.

    Given the candidates already found for one search plus the captured
    Algolia request (if any), this:
      1. Checks ambiguity and weak-match/ABV-mismatch on the current set.
      2. Checks whether the top candidate merely adds a release/vintage
         qualifier not present in the menu name (v24 trigger).
      3. If any of those call for it, runs expand_algolia_candidates(),
         applies the exact-ABV-family preference, and recomputes ambiguity/
         weak-match against the expanded set -- with expected_abv passed
         through both times, so a unique exact-ABV sibling can resolve an
         otherwise-ambiguous release family.

    Used by both search_one() (the primary search) and
    run_search_fallback_attempt() (the brewery/beer-only retries), so this
    decision only has one implementation to keep correct.
    """
    ambiguity_reason = detect_candidate_ambiguity(
        candidates,
        expected_beer=expected_beer,
        expected_abv=expected_abv,
    )

    best = candidates[0] if candidates else None

    abv_mismatch = (
        best is not None
        and expected_abv is not None
        and best.get("abv") is not None
        and abs(expected_abv - best["abv"]) >= ABV_MISMATCH_DIFF
    )

    weak_match = (
        best is None
        or best.get("score", 0) < min_score
        or abv_mismatch
    )

    release_qualifier_trigger = (
        best is not None
        and candidate_adds_release_qualifier(
            expected_beer,
            best.get("name"),
        )
    )

    same_abv_family_trigger = same_abv_family_discovery_trigger(
        candidates,
        expected_beer,
        expected_abv,
    )

    needs_expansion = bool(
        algolia_request
        and initial_nb_hits != 0
        and (
            ambiguity_reason
            or weak_match
            or release_qualifier_trigger
            or same_abv_family_trigger
        )
    )

    expanded_candidates = []
    expansion_diagnostics = None
    abv_sorted_diagnostics = None
    if needs_expansion:
        # Only clearly high brewery-like targets use Untappd's Highest ABV
        # replica. Low-ABV targets deliberately stay on the normal Most
        # Popular expansion because broad 0% result bands made the ascending
        # scan expensive without providing a safe stopping boundary.
        abv_sort_strategy = _abv_sorted_strategy(expected_abv)
        use_abv_sorted_probe = bool(
            abv_sort_strategy

            and (
                _is_brewery_like_input(
                    candidates, expected_beer, expected_brewery,
                )
                or _is_brewery_like_initial_page(
                    initial_algolia_page, expected_beer, expected_brewery,
                )
            )
        )

        if use_abv_sorted_probe:
            sorted_candidates, abv_sorted_diagnostics = scan_abv_sorted_ambiguity(
                page, algolia_request, search_query, expected_beer, expected_abv,
                min_score, abv_sort_strategy,
            )

            if _expansion_was_rate_limited(abv_sorted_diagnostics):
                return {
                    "candidates": candidates,
                    "ambiguity_reason": ambiguity_reason,
                    "weak_match": weak_match,
                    "release_qualifier_trigger": release_qualifier_trigger,
                    "same_abv_family_trigger": same_abv_family_trigger,
                    "needs_expansion": needs_expansion,
                    "expanded_candidates": [],
                    "expansion_diagnostics": None,
                    "abv_sorted_diagnostics": abv_sorted_diagnostics,
                    "rate_limited": True,
                }

            if abv_sorted_diagnostics.get("ambiguity_established"):
                candidates = sorted_candidates
                expanded_candidates = sorted_candidates
                best = candidates[0]
                ambiguity_reason = (
                    "Brewery-like input matches multiple "
                    f"{expected_abv:g}% beers"
                )
                weak_match = False

        if not (
            abv_sorted_diagnostics
            and abv_sorted_diagnostics.get("ambiguity_established")
        ):
            expanded_candidates, expansion_diagnostics = expand_algolia_candidates(
                page,
                algolia_request,
                search_query,
                expected_beer=expected_beer,
                expected_brewery=expected_brewery,
                expected_abv=expected_abv,
                initial_page=initial_algolia_page,
                min_score=min_score,
            )

            if expanded_candidates:
                candidates = expanded_candidates
                candidates, _ = apply_exact_abv_family_preference(
                    candidates,
                    expected_beer,
                    expected_abv,
                )
                best = candidates[0]

                ambiguity_reason = detect_candidate_ambiguity(
                    candidates,
                    expected_beer=expected_beer,
                    expected_abv=expected_abv,
                )

                if expansion_diagnostics.get("ambiguity_early_stopped"):
                    ambiguity_reason = (
                        "Brewery-like input matches multiple "
                        f"{expected_abv:g}% beers"
                    )

                abv_mismatch = (
                    expected_abv is not None
                    and best.get("abv") is not None
                    and abs(expected_abv - best["abv"]) >= ABV_MISMATCH_DIFF
                )

                weak_match = (
                    best.get("score", 0) < min_score
                    or abv_mismatch
                )

    return {
        "candidates": candidates,
        "ambiguity_reason": ambiguity_reason,
        "weak_match": weak_match,
        "release_qualifier_trigger": release_qualifier_trigger,
        "same_abv_family_trigger": same_abv_family_trigger,
        "needs_expansion": needs_expansion,
        "expanded_candidates": expanded_candidates,
        "expansion_diagnostics": expansion_diagnostics,
        "abv_sorted_diagnostics": abv_sorted_diagnostics,
        "rate_limited": (
            _expansion_was_rate_limited(expansion_diagnostics)
            or _expansion_was_rate_limited(abv_sorted_diagnostics)
        ),
    }



def _run_ui_page0_search_transport(
    page: Any,
    search_query: str,
    include_search_urls: bool = False,
    *,
    recovery: bool = False,
) -> SearchTransportResult:
    """Run one UI-triggered page-0 search and capture a fresh request template."""
    search_box = _timed_matcher_call(
        "search page -> search box ready",
        search_query,
        lambda: open_search_box(page),
    )
    if search_box is None:
        return {
            "request_event": None,
            "events": [],
            "error": "Search box not found",
            "transport": "ui-recovery" if recovery else "ui-bootstrap",
        }

    capture = _timed_matcher_call(
        "network capture setup",
        search_query,
        lambda: start_search_network_capture(
            page, include_search_urls=include_search_urls
        ),
    )
    events = capture["network_events"] if include_search_urls else capture["response_events"]
    request_events = capture["request_events"]
    try:
        _timed_matcher_call(
            "search submit operation",
            search_query,
            lambda: submit_search(page, search_box, search_query),
        )
    except Exception as exc:
        return {
            "request_event": None,
            "events": events,
            "error": str(exc),
            "transport": "ui-recovery" if recovery else "ui-bootstrap",
        }
    finally:
        stop_search_network_capture(page, capture)

    request_event = next(
        (
            event
            for event in reversed(request_events)
            if any(
                normalize(req.get("query") or "") == normalize(search_query)
                for req in (event.get("algolia_requests") or [])
            )
        ),
        None,
    )
    remembered = remember_search_transport_template(request_event, recovery=recovery)
    if recovery and not remembered:
        return {
            "request_event": request_event,
            "events": events,
            "error": "UI recovery did not capture a reusable Algolia request template",
            "transport": "ui-recovery",
        }
    return {
        "request_event": request_event,
        "events": events,
        "error": None,
        "transport": "ui-recovery" if recovery else "ui-bootstrap",
    }


def _run_page0_search_transport(
    page: Any,
    search_query: str,
    include_search_urls: bool = False,
) -> SearchTransportResult:
    """Return one page-0 Algolia search using v73's serial self-healing transport.

    The first search captures the live UI request shape. Subsequent searches use
    browser-context fetch(). A non-429 direct transport error invalidates the
    cached shape and gets exactly one UI recovery attempt for the same query;
    the successful UI request becomes the new template for later items. HTTP
    429 is never retried. Matching remains entirely downstream of this helper.
    """
    if not search_transport_template_available():
        return _run_ui_page0_search_transport(
            page, search_query, include_search_urls=include_search_urls
        )

    request_event, response_event, error = _timed_matcher_call(
        "direct Algolia search operation",
        search_query,
        lambda: fetch_authoritative_algolia_search(page, search_query),
    )
    events = [event for event in (request_event, response_event) if event is not None]

    # Preserve v72's fail-fast 429 semantics. Rate limiting is not evidence
    # that the request template is stale, and a UI retry would add traffic.
    if response_event is not None and response_event.get("status") == RATE_LIMIT_HTTP_STATUS:
        return {
            "request_event": request_event,
            "events": events,
            "error": error,
            "transport": "browser-fetch",
        }

    if error is None:
        return {
            "request_event": request_event,
            "events": events,
            "error": None,
            "transport": "browser-fetch",
        }

    # v73 self-healing: one stale/broken direct request must not poison every
    # remaining item. Discard it, recover this same query through the UI once,
    # and recapture a new live request shape. There is deliberately no loop.
    invalidate_search_transport_template()
    recovery_result = _run_ui_page0_search_transport(
        page,
        search_query,
        include_search_urls=include_search_urls,
        recovery=True,
    )
    recovery_ok = recovery_result.get("error") is None
    note_search_transport_recovery(recovery_ok)
    return recovery_result

def run_search_fallback_attempt(
    page,
    search_query,
    min_score,
    expected_beer=None,
    expected_brewery=None,
    expected_abv=None,
):
    """Run one conservative fallback search using the current v73 transport."""
    request_count_before = _ALGOLIA_DEBUG_STATS["beer_requests"]

    transport = _run_page0_search_transport(
        page, search_query, include_search_urls=False
    )
    algolia_request = transport["request_event"]
    response_events = transport["events"]
    transport_error = transport.get("error")

    algolia_status = _matching_algolia_response_status(
        response_events, search_query
    )
    if algolia_status == RATE_LIMIT_HTTP_STATUS:
        return {
            "query": search_query,
            "candidates": [],
            "ambiguity_reason": None,
            "weak_match": True,
            "algolia_request": algolia_request,
            "initial_algolia_page": None,
            "expanded_candidates": [],
            "expansion_diagnostics": None,
            "search_diagnostics": {},
            "rate_limited": True,
            "error": "Untappd/Algolia rate limited the search (HTTP 429)",
            "algolia_requests_this_attempt": (
                _ALGOLIA_DEBUG_STATS["beer_requests"] - request_count_before
            ),
        }

    if transport_error is not None:
        return {
            "query": search_query,
            "candidates": [],
            "ambiguity_reason": None,
            "weak_match": True,
            "algolia_request": algolia_request,
            "initial_algolia_page": None,
            "expanded_candidates": [],
            "expansion_diagnostics": None,
            "search_diagnostics": {},
            "rate_limited": False,
            "error": f"Search transport failed: {transport_error}",
            "algolia_requests_this_attempt": (
                _ALGOLIA_DEBUG_STATS["beer_requests"] - request_count_before
            ),
        }

    initial_algolia_page = _matching_algolia_initial_page(
        response_events, search_query
    )
    candidates = _timed_matcher_call(
        "Algolia candidate construction",
        search_query,
        lambda: _algolia_page0_candidates(
            initial_algolia_page,
            search_query,
            expected_beer=expected_beer,
            expected_brewery=expected_brewery,
            expected_abv=expected_abv,
        ),
    )
    search_diagnostics = {
        "algolia_hits_on_page": len((initial_algolia_page or {}).get("hits") or []),
        "candidates_passing_filter": len(candidates),
    }

    evaluation = evaluate_and_expand_candidates(
        page,
        search_query,
        candidates,
        algolia_request,
        min_score,
        expected_beer=expected_beer,
        expected_brewery=expected_brewery,
        expected_abv=expected_abv,
        initial_nb_hits=_matching_algolia_nb_hits(
            response_events, search_query
        ),
        initial_algolia_page=initial_algolia_page,
    )

    return {
        "query": search_query,
        "candidates": evaluation["candidates"],
        "ambiguity_reason": evaluation["ambiguity_reason"],
        "weak_match": evaluation["weak_match"],
        "algolia_request": algolia_request,
        "initial_algolia_page": initial_algolia_page,
        "expanded_candidates": evaluation["expanded_candidates"],
        "expansion_diagnostics": evaluation["expansion_diagnostics"],
        "abv_sorted_diagnostics": evaluation.get("abv_sorted_diagnostics"),
        "search_diagnostics": search_diagnostics,
        "rate_limited": evaluation.get("rate_limited", False),
        "error": (
            "Untappd/Algolia rate limited the search (HTTP 429)"
            if evaluation.get("rate_limited")
            else None
        ),
        "algolia_requests_this_attempt": (
            _ALGOLIA_DEBUG_STATS["beer_requests"] - request_count_before
        ),
    }


# ============================================================
# Search one beer
# ============================================================

def _alternative_from_candidate(item: CandidateRecord) -> AlternativeRecord:
    """Project one scored candidate into the compact ambiguity contract."""
    return {
        "name": item["name"],
        "score": item["score"],
        "abv": item.get("abv"),
        "brewery": item.get("brewery"),
        "rating": item.get("rating_score"),
        "ratings": item.get("rating_count"),
        "type_name": item.get("type_name"),
        "url": item.get("url"),
    }


def _search_one_impl(
    page: Any,
    query: str,
    min_score: float = DEFAULT_MIN_SCORE,
    debug: bool = False,
    expected_beer: Optional[str] = None,
    expected_brewery: Optional[str] = None,
    expected_abv: Optional[float] = None,
    expected_style: Optional[str] = None,
) -> MatchResult:
    _reset_beer_algolia_debug_stats()

    transport = _run_page0_search_transport(
        page, query, include_search_urls=True
    )
    algolia_request = transport["request_event"]
    network_events = transport["events"]
    transport_error = transport.get("error")

    algolia_status = _matching_algolia_response_status(
        network_events,
        query,
    )

    if algolia_status == RATE_LIMIT_HTTP_STATUS:
        if debug:
            _print_algolia_network_summary(rate_limited_query=query)
        return {
            "query": query,
            "status": "rate_limited",
            "reason": "Untappd/Algolia rate limited the search (HTTP 429)",
            "http_status": RATE_LIMIT_HTTP_STATUS,
        }

    if transport_error is not None:
        return {
            "query": query,
            "status": "failed",
            "reason": f"Search transport failed: {transport_error}",
        }

    primary_nb_hits = _matching_algolia_nb_hits(network_events, query)
    primary_algolia_page = _matching_algolia_initial_page(
        network_events, query
    )

    candidates = _timed_matcher_call(
        "Algolia candidate construction",
        query,
        lambda: _algolia_page0_candidates(
            primary_algolia_page,
            query,
            expected_beer=expected_beer,
            expected_brewery=expected_brewery,
            expected_abv=expected_abv,
        ),
    )
    search_diagnostics = {
        "algolia_hits_on_page": len((primary_algolia_page or {}).get("hits") or []),
        "candidates_passing_filter": len(candidates),
    }

    if debug:
        displayed_count = min(len(candidates), 10)

        print()
        print("Algolia page-0 candidate diagnostics:")
        print(
            f"  hits returned on captured page 0: "
            f"{search_diagnostics.get('algolia_hits_on_page', 0)}"
        )
        print(
            f"  candidates passing query filter: "
            f"{search_diagnostics.get('candidates_passing_filter', 0)}"
        )
        print(
            f"  candidates displayed below: "
            f"{displayed_count}"
        )

        print()
        print("Algolia diagnostics:")
        print(
            f"  requests captured for primary search: "
            f"{_ALGOLIA_DEBUG_STATS['beer_requests']}"
        )

        algolia_events = [
            event
            for event in network_events
            if "algolia.net/1/indexes" in (event.get("url") or "").lower()
        ]

        if not algolia_events:
            print("  no Algolia request captured")
        else:
            request_event = next(
                (
                    event
                    for event in reversed(algolia_events)
                    if event.get("kind") == "request"
                    and any(
                        normalize(req.get("query") or "") == normalize(query)
                        for req in (event.get("algolia_requests") or [])
                    )
                ),
                None,
            )
            response_event = next(
                (
                    event
                    for event in reversed(algolia_events)
                    if event.get("kind") == "response"
                    and any(
                        normalize(req.get("query") or "") == normalize(query)
                        for req in (event.get("algolia_requests") or [])
                    )
                ),
                None,
            )

            if request_event:
                print(
                    f"  request: {request_event.get('method')} "
                    f"[{request_event.get('resource_type')}]"
                )

                reqs = request_event.get("algolia_requests") or []

                if not reqs:
                    print("    request body could not be parsed")
                else:
                    for i, req in enumerate(reqs, start=1):
                        print(
                            f"    query {i}: "
                            f"index={req.get('indexName')!r}, "
                            f"query={req.get('query')!r}, "
                            f"page={req.get('page')!r}, "
                            f"hitsPerPage={req.get('hitsPerPage')!r}"
                        )

                        if req.get("filters"):
                            print(
                                f"      filters={req.get('filters')!r}"
                            )

            if response_event:
                print(
                    f"  response: HTTP {response_event.get('status')}"
                )

                summaries = response_event.get("algolia_response") or []

                if not summaries:
                    err = response_event.get("algolia_response_error")
                    if err:
                        print(
                            f"    response JSON could not be parsed: {err}"
                        )
                    else:
                        print(
                            "    response contained no summarized result sets"
                        )
                else:
                    for i, summary in enumerate(summaries, start=1):
                        print(
                            f"    result {i}: "
                            f"index={summary.get('index')!r}, "
                            f"nbHits={summary.get('nbHits')}, "
                            f"page={summary.get('page')}, "
                            f"nbPages={summary.get('nbPages')}, "
                            f"hitsPerPage={summary.get('hitsPerPage')}, "
                            f"hitsReturned={summary.get('hitsReturned')}"
                        )

                        if summary.get("hitKeys"):
                            print(
                                "      sample hit fields: "
                                + ", ".join(summary["hitKeys"])
                            )

                        sample_hits = summary.get("sampleHits") or []
                        if sample_hits:
                            print("      first returned hits:")
                            for hit in sample_hits[:5]:
                                print(
                                    f"        - {hit.get('brewery_name')} — "
                                    f"{hit.get('beer_name')} "
                                    f"(ABV {hit.get('beer_abv')}, "
                                    f"rating {hit.get('rating_score')}, "
                                    f"ratings {hit.get('rating_count')})"
                                )

        print()
        print("Candidates:")

        for i, item in enumerate(
            candidates[:10],
            start=1,
        ):
            print(
                f"{i}. "
                f"{item['name']} "
                f"(score "
                f"{item['score']:.3f}, "
                f"ABV {item.get('abv') if item.get('abv') is not None else 'N/A'})"
            )

            print(
                f"   {item['url']}"
            )


    # Decide whether this search needs the slower, complete Algolia pass.
    evaluation = _timed_matcher_call(
        "candidate evaluation / expansion",
        query,
        lambda: evaluate_and_expand_candidates(
            page,
            query,
            candidates,
            algolia_request,
            min_score,
            expected_beer=expected_beer,
            expected_brewery=expected_brewery,
            expected_abv=expected_abv,
            initial_nb_hits=primary_nb_hits,
            initial_algolia_page=primary_algolia_page,
        ),
    )

    candidates = evaluation["candidates"]
    ambiguity_reason = evaluation["ambiguity_reason"]
    release_qualifier_trigger = evaluation["release_qualifier_trigger"]
    needs_expansion = evaluation["needs_expansion"]
    expanded_candidates = evaluation["expanded_candidates"]
    expansion_diagnostics = evaluation["expansion_diagnostics"]
    abv_sorted_diagnostics = evaluation.get("abv_sorted_diagnostics")

    if evaluation.get("rate_limited"):
        if debug:
            _print_algolia_network_summary(rate_limited_query=query)
        return {
            "query": query,
            "status": "rate_limited",
            "reason": "Untappd/Algolia rate limited the search (HTTP 429)",
            "http_status": RATE_LIMIT_HTTP_STATUS,
        }

    if debug and needs_expansion:
        print()
        print("Conditional Algolia expansion:")

        if release_qualifier_trigger:
            print(
                "  trigger: candidate adds release year "
                "not present in menu beer name"
            )

        if abv_sorted_diagnostics:
            print(
                "  ABV-sorted ambiguity scan: "
                f"{abv_sorted_diagnostics.get('index')}"
            )
            print(
                "  sort direction: "
                f"{abv_sorted_diagnostics.get('direction')} "
                f"({abv_sorted_diagnostics.get('sort_label')})"
            )
            print(
                f"  target ABV: "
                f"{abv_sorted_diagnostics.get('target_abv'):g}%"
            )
            if abv_sorted_diagnostics.get("threshold_reason"):
                print("  strategy reason: " + abv_sorted_diagnostics.get("threshold_reason"))
            print(
                f"  sorted pages: "
                f"{abv_sorted_diagnostics.get('pages_succeeded', 0)}/"
                f"{abv_sorted_diagnostics.get('pages_requested', 0)} succeeded"
            )
            print(
                f"  sorted raw hits fetched: "
                f"{abv_sorted_diagnostics.get('raw_hits', 0)}"
            )
            direction = abv_sorted_diagnostics.get("direction")
            if direction == "ascending":
                print(
                    "  crossed above target ABV: "
                    + ("yes" if abv_sorted_diagnostics.get("crossed_above_target") else "no")
                )
            else:
                print(
                    "  crossed below target ABV: "
                    + ("yes" if abv_sorted_diagnostics.get("crossed_below_target") else "no")
                )
            print(
                "  target ABV band exhausted: "
                + ("yes" if abv_sorted_diagnostics.get("target_band_exhausted") else "no")
            )
            print(
                f"  exact-ABV brewery candidates: "
                f"{abv_sorted_diagnostics.get('exact_abv_candidates', 0)}"
            )
            print(
                "  ambiguity established by sorted scan: "
                + ("yes" if abv_sorted_diagnostics.get("ambiguity_established") else "no")
            )
            if abv_sorted_diagnostics.get("stopped_after_page") is not None:
                print(
                    f"  sorted scan stopped after page: "
                    f"{abv_sorted_diagnostics.get('stopped_after_page')}"
                )
            if abv_sorted_diagnostics.get("capped"):
                print("  sorted scan capped: yes")
            for err in abv_sorted_diagnostics.get("errors") or []:
                print(f"  sorted scan error: {err}")

        if expansion_diagnostics:
            print(
                "  primary page 0 reused: "
                + (
                    "yes"
                    if expansion_diagnostics.get("pages_reused", 0)
                    else "no"
                )
            )
            if expansion_diagnostics.get("pages_reused", 0):
                print(
                    f"  primary hits reused: "
                    f"{expansion_diagnostics.get('reused_hits', 0)}"
                )
            print(
                f"  additional pages: "
                f"{expansion_diagnostics.get('pages_succeeded', 0)}/"
                f"{expansion_diagnostics.get('pages_requested', 0)} succeeded"
            )
            print(
                f"  page limit: "
                f"{expansion_diagnostics.get('page_limit')}"
            )
            if expansion_diagnostics.get("capped"):
                print(
                    "  expansion capped: yes "
                    "(remaining Algolia pages were not requested)"
                )
            if expansion_diagnostics.get("ambiguity_early_stopped"):
                print(
                    "  ambiguity early stop: yes "
                    "(input is brewery-like and already matches multiple exact-ABV beers)"
                )
                print(
                    f"  exact-ABV beers establishing ambiguity: "
                    f"{expansion_diagnostics.get('ambiguity_early_stop_candidate_count', 0)}"
                )
                print(
                    f"  stopped after Algolia page: "
                    f"{expansion_diagnostics.get('ambiguity_early_stop_after_page')}"
                )
            print(
                f"  Algolia total: "
                f"{expansion_diagnostics.get('nbHits')} hits across "
                f"{expansion_diagnostics.get('nbPages')} pages"
            )
            print(
                f"  additional raw hits fetched: "
                f"{expansion_diagnostics.get('raw_hits', 0)}"
            )
            print(
                f"  total raw hits scored: "
                f"{expansion_diagnostics.get('raw_hits_scored', 0)}"
            )
            print(
                f"  unique candidates scored: "
                f"{expansion_diagnostics.get('unique_candidates', 0)}"
            )

            for err in expansion_diagnostics.get("errors") or []:
                print(f"  error: {err}")

        if expanded_candidates:
            print("  top expanded candidates:")
            for item in expanded_candidates[:10]:
                print(
                    f"    - {item['name']} "
                    f"(score {item['score']:.3f}, "
                    f"ABV {item.get('abv') if item.get('abv') is not None else 'N/A'})"
                )

    # v23: if the full structured query still has poor recall after the
    # normal DOM/Algolia path, retry with progressively less brittle search
    # strings. The original brewery and ABV remain verification signals.
    current_best = candidates[0] if candidates else None
    current_abv_mismatch = (
        current_best is not None
        and expected_abv is not None
        and current_best.get("abv") is not None
        and abs(expected_abv - current_best["abv"]) >= ABV_MISMATCH_DIFF
    )
    current_weak_match = (
        current_best is None
        or current_best.get("score", 0) < min_score
        or current_abv_mismatch
    )

    fallback_queries = (
        build_search_fallback_queries(
            query,
            expected_beer=expected_beer,
            expected_brewery=expected_brewery,
            expected_style=expected_style,
            enable_trailing_relaxation=(primary_nb_hits == 0),
        )
        if current_weak_match
        else []
    )

    fallback_query_used = None
    fallback_started = perf_counter() if debug_timing_enabled() and fallback_queries else None

    for fallback_attempt_number, fallback_query in enumerate(
        fallback_queries,
        start=1,
    ):
        if debug:
            print()
            print(
                f"Search fallback {fallback_attempt_number}/"
                f"{len(fallback_queries)}: {fallback_query}"
            )

        fallback = run_search_fallback_attempt(
            page,
            fallback_query,
            min_score=min_score,
            expected_beer=expected_beer,
            expected_brewery=expected_brewery,
            expected_abv=expected_abv,
        )

        fallback_candidates = fallback.get("candidates") or []

        # v47: relaxed trailing-token searches are discovery-only. Require
        # brewery agreement and a returned beer name that is the leading/base
        # identity of the original menu beer before accepting the result set.
        trailing_relaxation_queries = {
            normalize(item)
            for item in trailing_relaxation_search_queries(
                expected_beer, expected_brewery
            )
        }
        if normalize(fallback_query) in trailing_relaxation_queries:
            compatible_candidates = [
                item for item in fallback_candidates
                if candidate_has_brewery_overlap(item, expected_brewery)
                and candidate_matches_trailing_relaxed_identity(item, expected_beer)
            ]
            if debug and len(compatible_candidates) != len(fallback_candidates):
                print(
                    f"  trailing-relaxation identity filter: "
                    f"{len(fallback_candidates) - len(compatible_candidates)} "
                    f"candidate(s) rejected"
                )
            fallback_candidates = compatible_candidates
            fallback["candidates"] = compatible_candidates
            fallback["ambiguity_reason"] = detect_candidate_ambiguity(
                compatible_candidates,
                expected_beer=expected_beer,
                expected_abv=expected_abv,
            ) if compatible_candidates else None
            fallback["weak_match"] = (
                not compatible_candidates
                or compatible_candidates[0].get("score", 0) < min_score
            )

        # A beer-name-only fallback deliberately discards brewery search tokens.
        # If the menu supplied brewery identity, do not let an explicitly
        # unrelated brewery become a confident match merely through name/ABV.
        is_beer_only_fallback = (
            normalize(fallback_query) == normalize(final_query_cleanup(expected_beer or ""))
        )
        if is_beer_only_fallback and expected_brewery:
            compatible_candidates = [
                item for item in fallback_candidates
                if candidate_has_brewery_overlap(item, expected_brewery)
            ]
            if debug and len(compatible_candidates) != len(fallback_candidates):
                print(
                    f"  brewery contradiction filter: "
                    f"{len(fallback_candidates) - len(compatible_candidates)} "
                    f"unrelated candidate(s) rejected"
                )
            fallback_candidates = compatible_candidates
            fallback["candidates"] = compatible_candidates
            fallback["ambiguity_reason"] = detect_candidate_ambiguity(
                compatible_candidates,
                expected_beer=expected_beer,
                expected_abv=expected_abv,
            ) if compatible_candidates else None
            fallback["weak_match"] = (
                not compatible_candidates
                or compatible_candidates[0].get("score", 0) < min_score
            )

        if fallback.get("rate_limited"):
            if debug:
                print(
                    f"  Algolia requests this fallback: "
                    f"{fallback.get('algolia_requests_this_attempt', 0)}"
                )
                _print_algolia_network_summary(
                    rate_limited_query=fallback_query
                )
            return {
                "query": query,
                "status": "rate_limited",
                "reason": "Untappd/Algolia rate limited the search (HTTP 429)",
                "http_status": RATE_LIMIT_HTTP_STATUS,
            }

        if debug:
            print(
                f"  candidates: {len(fallback_candidates)}"
            )
            print(
                f"  Algolia requests this fallback: "
                f"{fallback.get('algolia_requests_this_attempt', 0)}"
            )
            if fallback.get("expanded_candidates"):
                diagnostics = fallback.get("expansion_diagnostics") or {}
                reuse_note = (
                    "page 0 reused; "
                    if diagnostics.get("pages_reused", 0)
                    else "page 0 not reused; "
                )
                print(
                    f"  Algolia expansion: "
                    f"{diagnostics.get('unique_candidates', 0)} candidates "
                    f"from {diagnostics.get('nbHits')} hits; "
                    f"{reuse_note}"
                    f"{diagnostics.get('pages_requested', 0)} additional "
                    f"page requests attempted"
                )
                if diagnostics.get("capped"):
                    print(
                        f"  Algolia expansion capped at "
                        f"{diagnostics.get('page_limit')} pages"
                    )

            for item in fallback_candidates[:5]:
                print(
                    f"    - {item['name']} "
                    f"(score {item['score']:.3f}, "
                    f"ABV {item.get('abv') if item.get('abv') is not None else 'N/A'})"
                )

        if not fallback_candidates:
            continue

        # Prefer the fallback result set as soon as it produces a plausible
        # match or a meaningful ambiguity. If it remains weak, continue to
        # the next, broader fallback (ultimately beer-name-only).
        if (
            fallback.get("ambiguity_reason")
            or not fallback.get("weak_match")
        ):
            candidates = fallback_candidates
            ambiguity_reason = fallback.get("ambiguity_reason")
            expanded_candidates = fallback.get("expanded_candidates") or []
            expansion_diagnostics = fallback.get("expansion_diagnostics")
            fallback_query_used = fallback_query
            # The winning candidate now comes from this fallback query, not
            # the original one -- use its initial Algolia page (if any) for
            # later brewery-metadata recovery instead of the stale original.
            primary_algolia_page = fallback.get("initial_algolia_page")
            break

        # Keep the strongest weak fallback as a last-resort diagnostic/result
        # set, but continue trying broader search text.
        if (
            not candidates
            or fallback_candidates[0].get("score", 0)
            > candidates[0].get("score", 0)
        ):
            candidates = fallback_candidates
            ambiguity_reason = fallback.get("ambiguity_reason")
            expanded_candidates = fallback.get("expanded_candidates") or []
            expansion_diagnostics = fallback.get("expansion_diagnostics")
            fallback_query_used = fallback_query
            primary_algolia_page = fallback.get("initial_algolia_page")

    if fallback_started is not None:
        _record_matcher_phase(
            "fallback orchestration", query, perf_counter() - fallback_started
        )

    if debug and fallback_query_used:
        print(
            f"  using fallback result set from: "
            f"{fallback_query_used}"
        )

    if debug:
        _print_algolia_network_summary()

    if not candidates:
        return {
            "query": query,
            "status": "failed",
            "reason": "No matching beer found",
        }

    same_abv_variants = same_abv_family_variants(
        candidates,
        expected_beer,
        expected_abv,
    )

    # If the expanded result set contains multiple variants from the same
    # named family at the exact menu ABV, that is the most useful ambiguity
    # explanation for the user. Prefer it over a generic near-tie message.
    if len(same_abv_variants) >= 2:
        best = candidates[0]

        return {
            "query": query,
            "status": "ambiguous",
            "match": best["name"],
            "score": best["score"],
            "url": best.get("url"),
            "reason": f"Multiple {expected_abv:g}% variants found",
            "alternatives": [
                _alternative_from_candidate(item) for item in candidates[:10]
            ],
            "same_abv_variants": [
                _alternative_from_candidate(item) for item in same_abv_variants
            ],
            "search_expanded": bool(expanded_candidates),
            "search_fallback": fallback_query_used,
            "expanded_total_hits": (
                expansion_diagnostics.get("nbHits")
                if expansion_diagnostics
                else None
            ),
        }

    if ambiguity_reason:
        best = candidates[0]

        return {
            "query": query,
            "status": "ambiguous",
            "match": best["name"],
            "score": best["score"],
            "url": best.get("url"),
            "reason": ambiguity_reason,
            "alternatives": [
                _alternative_from_candidate(item) for item in candidates[:10]
            ],
            "same_abv_variants": [],
            "search_expanded": bool(expanded_candidates),
            "search_fallback": fallback_query_used,
            "expanded_total_hits": (
                expansion_diagnostics.get("nbHits")
                if expansion_diagnostics
                else None
            ),
        }

    best = candidates[0]

    # If both the menu and the search result expose ABV, reject a large
    # mismatch even when the textual match looks convincing.
    if (
        expected_abv is not None
        and best.get("abv") is not None
        and abs(expected_abv - best["abv"]) >= 1.00
    ):
        return {
            "query": query,
            "status": "low_confidence",
            "match": best["name"],
            "score": best["score"],
            "url": best["url"],
            "reason": (
                f"ABV mismatch: menu {expected_abv:g}% vs "
                f"Untappd {best['abv']:g}%"
            ),
        }

    if best["score"] < min_score:
        return {
            "query": query,
            "status": "low_confidence",
            "match": best["name"],
            "score": best["score"],
            "url": best["url"],
        }

    brewery = best.get("brewery")
    if not brewery or normalize(brewery) == "unknown":
        brewery = extract_brewery_from_result(
            best["text"],
            best["name"],
        )
    if not brewery or normalize(brewery) == "unknown":
        brewery = _brewery_from_algolia_initial_page(
            primary_algolia_page, best
        )

    info = _confirmed_info_from_algolia(best, brewery)
    if info is None:
        _record_algolia_confirmation(detail_fallback=True)
        info = _timed_matcher_call(
            "detail-page operation total",
            query,
            lambda: extract_beer_info(
                page,
                best["url"],
                brewery_from_search=brewery,
            ),
        )
    else:
        _record_algolia_confirmation(detail_fallback=False)

    type_name = best.get("type_name")
    if not type_name:
        type_name = _type_name_from_algolia_initial_page(
            primary_algolia_page, best
        )
    info["type_name"] = type_name

    info.update({
        "query": query,
        "status": "ok",
        "score": best["score"],
        "search_text": clean_block_text(
            best["text"]
        ),
        "search_fallback": fallback_query_used,
    })

    return info






def search_one(
    page: Any,
    query: str,
    min_score: float = DEFAULT_MIN_SCORE,
    debug: bool = False,
    expected_beer: Optional[str] = None,
    expected_brewery: Optional[str] = None,
    expected_abv: Optional[float] = None,
    expected_style: Optional[str] = None,
) -> MatchResult:
    """Public matcher entry point with measurement-only total timing."""
    global _CURRENT_MATCHER_PHASE_SECONDS
    if not debug_timing_enabled():
        return _search_one_impl(
            page, query, min_score, debug, expected_beer, expected_brewery,
            expected_abv, expected_style
        )
    _CURRENT_MATCHER_PHASE_SECONDS = 0.0
    started = perf_counter()
    try:
        return _search_one_impl(
            page, query, min_score, debug, expected_beer, expected_brewery,
            expected_abv, expected_style
        )
    finally:
        elapsed = perf_counter() - started
        _record_matcher_total(query, elapsed, _CURRENT_MATCHER_PHASE_SECONDS)


# ============================================================
# Main
# ============================================================
