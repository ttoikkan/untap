"""Pure brewery evidence policy; callers own adoption and eligibility decisions."""
from dataclasses import dataclass
from typing import Literal, Optional
from untap.parser import normalize


@dataclass(frozen=True)
class BreweryVerdict:
    kind: Literal["compatible", "conflicting", "unknown"]
    reason: str

    @property
    def permits_candidate(self) -> bool:
        return self.kind != "conflicting"


def meaningful_brewery_words(text: Optional[str]) -> set[str]:
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


def brewery_verdict(candidate_brewery: Optional[str], expected_brewery: Optional[str]) -> BreweryVerdict:
    """Compare normalized evidence, retaining the historical short-name behavior."""
    if not expected_brewery:
        return BreweryVerdict("unknown", "Menu brewery is unspecified")
    if not candidate_brewery or normalize(candidate_brewery) == "unknown":
        return BreweryVerdict("unknown", "Candidate brewery is unknown")
    expected_words = meaningful_brewery_words(expected_brewery)
    candidate_words = meaningful_brewery_words(candidate_brewery)
    if not expected_words or not candidate_words:
        generic = {"brew", "brewing", "brewery", "company", "co", "inc",
                   "llc", "ltd", "limited", "corp", "corporation", "plc", "x"}
        expected_short = set(normalize(expected_brewery).split()) - generic
        candidate_short = set(normalize(candidate_brewery).split()) - generic
        if not expected_short or not candidate_short:
            return BreweryVerdict("unknown", "Brewery evidence contains only generic words")
        compatible = candidate_short <= expected_short or expected_short <= candidate_short
    else:
        compatible = bool(expected_words & candidate_words)
    if compatible:
        return BreweryVerdict("compatible", "Brewery shares menu identity evidence")
    return BreweryVerdict("conflicting", f"Brewery does not match menu brewery {expected_brewery}")
