"""Manual live-production smoke check for Untap's external Untappd dependency.

This module intentionally performs a tiny serial live probe. It is not part of
normal deterministic CI and it does not attempt to measure or discover rate
limits. The goal is to answer one operational question on demand: does the
current Untappd UI/bootstrap + Algolia transport contract still work end to end?
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from untap_matcher import (
    get_algolia_confirmation_stats,
    reset_algolia_confirmation_stats,
    search_one,
)
from untap_untappd import (
    get_search_transport_authority_stats,
    reset_search_transport_authority_state,
    search_transport_template_available,
)
from untap_types import MatchResult


SMOKE_EXIT_HEALTHY = 0
SMOKE_EXIT_BOOTSTRAP = 2
SMOKE_EXIT_DIRECT_TRANSPORT = 3
SMOKE_EXIT_RESPONSE_CONTRACT = 4
SMOKE_EXIT_IDENTITY = 5
SMOKE_EXIT_RATE_LIMITED = 6
SMOKE_EXIT_RUNTIME = 7


@dataclass(frozen=True)
class SmokeFixture:
    query: str
    expected_beer: str
    expected_brewery: str
    expected_abv: float


# Two deliberately ordinary, long-lived beer identities. Mutable rating/count
# values are never asserted. The first search exercises UI bootstrap/template
# capture; the second must exercise the authoritative direct transport.
_SMOKE_FIXTURES: Tuple[SmokeFixture, SmokeFixture] = (
    SmokeFixture(
        query="Brasserie du Bas-Canada Pivo Hull",
        expected_beer="Pivo Hull",
        expected_brewery="Brasserie du Bas-Canada",
        expected_abv=4.1,
    ),
    SmokeFixture(
        query="Brujos Lament",
        expected_beer="Lament",
        expected_brewery="Brujos",
        expected_abv=5.3,
    ),
)


@dataclass
class SmokeCheck:
    label: str
    status: str
    detail: str = ""


def _normalized_identity(value: Optional[str]) -> str:
    if value is None:
        return ""
    return " ".join(value.casefold().replace("–", "-").replace("—", "-").split())


def _identity_matches(result: MatchResult, fixture: SmokeFixture) -> bool:
    beer = _normalized_identity(result.get("beer"))
    brewery = _normalized_identity(result.get("brewery"))
    expected_beer = _normalized_identity(fixture.expected_beer)
    expected_brewery = _normalized_identity(fixture.expected_brewery)
    return beer == expected_beer and expected_brewery in brewery


def _confirmed_contract_is_usable(result: MatchResult) -> bool:
    rating = result.get("rating")
    ratings = result.get("ratings")
    abv = result.get("abv")
    url = result.get("url")
    return (
        isinstance(result.get("beer"), str)
        and bool(result.get("beer"))
        and isinstance(result.get("brewery"), str)
        and bool(result.get("brewery"))
        and isinstance(rating, (int, float))
        and not isinstance(rating, bool)
        and isinstance(ratings, int)
        and not isinstance(ratings, bool)
        and abv not in (None, "")
        and isinstance(url, str)
        and url.startswith("https://untappd.com/b/")
    )


def _print_checks(checks: List[SmokeCheck], exit_code: int) -> None:
    print()
    print("Untap live smoke test")
    print("=" * 70)
    for check in checks:
        suffix = f" — {check.detail}" if check.detail else ""
        print(f"{check.label:<32} {check.status}{suffix}")
    print()
    print("Rate-limit threshold probing     NOT PERFORMED")
    print("GitHub automation               NOT USED")
    print()
    print(f"Result: {'HEALTHY' if exit_code == SMOKE_EXIT_HEALTHY else 'UNHEALTHY'}")


def run_live_smoke_test(page: Any) -> int:
    """Run a tiny live Untappd integration probe and return a machine exit code."""
    checks: List[SmokeCheck] = []
    reset_search_transport_authority_state()
    reset_algolia_confirmation_stats()

    first_fixture, second_fixture = _SMOKE_FIXTURES

    try:
        first = search_one(
            page,
            first_fixture.query,
            expected_beer=first_fixture.expected_beer,
            expected_brewery=first_fixture.expected_brewery,
            expected_abv=first_fixture.expected_abv,
        )
    except Exception as exc:
        checks.append(SmokeCheck("UI bootstrap", "FAIL", str(exc)))
        _print_checks(checks, SMOKE_EXIT_RUNTIME)
        return SMOKE_EXIT_RUNTIME

    if first.get("status") == "rate_limited":
        checks.append(SmokeCheck("UI bootstrap", "FAIL", "HTTP 429"))
        checks.append(SmokeCheck("HTTP 429", "YES"))
        _print_checks(checks, SMOKE_EXIT_RATE_LIMITED)
        return SMOKE_EXIT_RATE_LIMITED

    if first.get("status") != "ok":
        checks.append(SmokeCheck("UI bootstrap", "FAIL", first.get("reason", "search failed")))
        _print_checks(checks, SMOKE_EXIT_BOOTSTRAP)
        return SMOKE_EXIT_BOOTSTRAP
    checks.append(SmokeCheck("UI bootstrap", "PASS"))

    if not search_transport_template_available():
        checks.append(SmokeCheck("Algolia template capture", "FAIL"))
        _print_checks(checks, SMOKE_EXIT_BOOTSTRAP)
        return SMOKE_EXIT_BOOTSTRAP
    checks.append(SmokeCheck("Algolia template capture", "PASS"))

    if not _confirmed_contract_is_usable(first):
        checks.append(SmokeCheck("Algolia response contract", "FAIL", "bootstrap result incomplete"))
        _print_checks(checks, SMOKE_EXIT_RESPONSE_CONTRACT)
        return SMOKE_EXIT_RESPONSE_CONTRACT

    if not _identity_matches(first, first_fixture):
        checks.append(SmokeCheck("Known beer identity", "FAIL", first.get("beer", "missing beer")))
        _print_checks(checks, SMOKE_EXIT_IDENTITY)
        return SMOKE_EXIT_IDENTITY

    try:
        second = search_one(
            page,
            second_fixture.query,
            expected_beer=second_fixture.expected_beer,
            expected_brewery=second_fixture.expected_brewery,
            expected_abv=second_fixture.expected_abv,
        )
    except Exception as exc:
        checks.append(SmokeCheck("Direct transport", "FAIL", str(exc)))
        _print_checks(checks, SMOKE_EXIT_RUNTIME)
        return SMOKE_EXIT_RUNTIME

    if second.get("status") == "rate_limited":
        checks.append(SmokeCheck("Direct transport", "FAIL", "HTTP 429"))
        checks.append(SmokeCheck("HTTP 429", "YES"))
        _print_checks(checks, SMOKE_EXIT_RATE_LIMITED)
        return SMOKE_EXIT_RATE_LIMITED

    transport_stats: Dict[str, Any] = get_search_transport_authority_stats()
    if second.get("status") != "ok" or int(transport_stats.get("direct_searches", 0)) < 1:
        detail = second.get("reason", "authoritative direct search was not observed")
        checks.append(SmokeCheck("Direct transport", "FAIL", detail))
        _print_checks(checks, SMOKE_EXIT_DIRECT_TRANSPORT)
        return SMOKE_EXIT_DIRECT_TRANSPORT
    checks.append(SmokeCheck("Direct transport", "PASS"))

    if not _confirmed_contract_is_usable(second):
        checks.append(SmokeCheck("Algolia response contract", "FAIL", "direct result incomplete"))
        _print_checks(checks, SMOKE_EXIT_RESPONSE_CONTRACT)
        return SMOKE_EXIT_RESPONSE_CONTRACT

    confirmation_stats = get_algolia_confirmation_stats()
    if (
        confirmation_stats.get("confirmed_from_algolia", 0) != 2
        or confirmation_stats.get("detail_page_fallbacks", 0) != 0
    ):
        checks.append(
            SmokeCheck(
                "Algolia response contract",
                "FAIL",
                "confirmed result required detail-page fallback",
            )
        )
        _print_checks(checks, SMOKE_EXIT_RESPONSE_CONTRACT)
        return SMOKE_EXIT_RESPONSE_CONTRACT
    checks.append(SmokeCheck("Algolia response contract", "PASS"))

    if not _identity_matches(second, second_fixture):
        checks.append(SmokeCheck("Known beer identity", "FAIL", second.get("beer", "missing beer")))
        _print_checks(checks, SMOKE_EXIT_IDENTITY)
        return SMOKE_EXIT_IDENTITY
    checks.append(SmokeCheck("Known beer identity", "PASS"))

    if int(transport_stats.get("direct_rate_limited", 0)):
        checks.append(SmokeCheck("HTTP 429", "YES"))
        _print_checks(checks, SMOKE_EXIT_RATE_LIMITED)
        return SMOKE_EXIT_RATE_LIMITED
    checks.append(SmokeCheck("HTTP 429", "NO"))
    checks.append(SmokeCheck("Self-healing path", "NOT EXERCISED"))

    _print_checks(checks, SMOKE_EXIT_HEALTHY)
    return SMOKE_EXIT_HEALTHY
