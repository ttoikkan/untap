import sys
import contextlib
from pathlib import Path
from time import perf_counter
from typing import Callable, Any, Iterator, TextIO, List, Optional, Sequence, TypedDict, Union

from untap.types import MatchResult, NormalizedMenuRecord
# Compatibility exports for source callers; implementation belongs to output.
from untap.run_output import CSV_FIELDS as CSV_FIELDS, save_csv as save_csv

from untap.matcher import (
    DEFAULT_MIN_SCORE,
    search_one,
    get_last_matcher_timing_seconds,
    reset_matcher_timing_stats,
)
from untap.transport import _reset_run_algolia_debug_stats, debug_timing_enabled

__all__ = [
    "debug_transcript",
    "get_batch_timing_stats",
    "print_batch_timing_summary",
    "read_queries_from_file",
    "reset_batch_timing_stats",
    "run_batch",
    "unattempted_result",
    # Compatibility exports for source callers; implementation belongs to untap.run_output.
    "CSV_FIELDS",
    "save_csv",
]


class _BatchTimingStats(TypedDict):
    count: int
    total_item_seconds: float
    min_item_seconds: Optional[float]
    max_item_seconds: Optional[float]
    batch_seconds: float
    outside_matcher_seconds: float


_BATCH_TIMING_STATS: _BatchTimingStats = {
    "count": 0,
    "total_item_seconds": 0.0,
    "min_item_seconds": None,
    "max_item_seconds": None,
    "batch_seconds": 0.0,
    "outside_matcher_seconds": 0.0,
}


def reset_batch_timing_stats() -> None:
    _BATCH_TIMING_STATS.update({
        "count": 0,
        "total_item_seconds": 0.0,
        "min_item_seconds": None,
        "max_item_seconds": None,
        "batch_seconds": 0.0,
        "outside_matcher_seconds": 0.0,
    })


def get_batch_timing_stats():
    return dict(_BATCH_TIMING_STATS)


def _record_item_timing(
    query: str,
    elapsed_seconds: float,
    resumed: bool = False,
    matcher_seconds: Optional[float] = None,
) -> None:
    stats = _BATCH_TIMING_STATS
    stats["count"] += 1
    stats["total_item_seconds"] += elapsed_seconds
    current_min = stats["min_item_seconds"]
    current_max = stats["max_item_seconds"]
    stats["min_item_seconds"] = (
        elapsed_seconds if current_min is None else min(current_min, elapsed_seconds)
    )
    stats["max_item_seconds"] = (
        elapsed_seconds if current_max is None else max(current_max, elapsed_seconds)
    )
    status_suffix = " [resumed]" if resumed else ""
    if matcher_seconds is not None:
        outside_matcher = max(0.0, elapsed_seconds - matcher_seconds)
        stats["outside_matcher_seconds"] += outside_matcher
        print(
            f"[timing] batch overhead outside matcher: {outside_matcher:.3f}s | {query}"
        )
    print(f"[timing] item total: {elapsed_seconds:.3f}s{status_suffix} | {query}")


def print_batch_timing_summary() -> None:
    if not debug_timing_enabled():
        return

    stats = _BATCH_TIMING_STATS
    count = stats["count"]
    print()
    print("Batch timing summary")
    print("=" * 70)
    if not count:
        print("No timed batch items.")
        return

    total = stats["total_item_seconds"]
    print(f"Timed batch items: {count}")
    print(f"Total per-item elapsed time: {total:.3f}s")
    print(f"Average item elapsed time: {total / count:.3f}s")
    print(f"Fastest item elapsed time: {stats['min_item_seconds']:.3f}s")
    print(f"Slowest item elapsed time: {stats['max_item_seconds']:.3f}s")
    print(f"Whole batch elapsed time: {stats['batch_seconds']:.3f}s")
    print(f"Batch overhead outside matcher: {stats['outside_matcher_seconds']:.3f}s")


# ============================================================
# Batch / persistence layer
# ============================================================
# v59: batch iteration, CSV persistence, and occurrence-aware resume/cache
# handling moved here from untap.py without intended behavior changes.
# This module consumes already-normalized menu records or plain query strings;
# it does not parse raw menu text and it does not perform direct browser or
# Algolia transport operations.


# ============================================================
# Input modes
# ============================================================

def read_queries_from_file(filename: str) -> List[str]:
    with open(
        filename,
        "r",
        encoding="utf-8",
    ) as f:
        return [
            line.strip()
            for line in f
            if line.strip()
        ]


def unattempted_result(item: Union[NormalizedMenuRecord, str], reason: str) -> MatchResult:
    result: MatchResult = {
        "query": item["query"] if isinstance(item, dict) else item,
        "status": "not_attempted", "reason": reason,
    }
    if isinstance(item, dict):
        abv = item.get("menu_abv")
        result.update({
            "original_menu_text": item.get("original"),
            "input_brewery": item.get("brewery") or "",
            "input_beer": item.get("beer") or "",
            "input_abv": "" if abv is None else f"{abv:g}",
            "input_style": item.get("style") or "",
        })
    return result


def run_batch(
    page: Any,
    items: Sequence[Union[NormalizedMenuRecord, str]],
    min_score: float = DEFAULT_MIN_SCORE,
    debug: bool = False,
    on_result: Optional[Callable[[MatchResult], None]] = None,
) -> List[MatchResult]:
    _reset_run_algolia_debug_stats()
    reset_batch_timing_stats()
    reset_matcher_timing_stats()
    timing_enabled = debug_timing_enabled()
    batch_started = perf_counter() if timing_enabled else None
    results = []
    total = len(items)

    for i, item in enumerate(
        items,
        start=1,
    ):
        item_started = perf_counter() if timing_enabled else None
        if isinstance(item, dict):
            query = item["query"]
            original = item.get("original")
            expected_beer = item.get("beer")
            expected_brewery = item.get("brewery")
            expected_abv = item.get("menu_abv")
            expected_style = item.get("style")
        else:
            query = item
            original = None
            expected_beer = None
            expected_brewery = None
            expected_abv = None
            expected_style = None

        print(
            f"[{i}/{total}] "
            f"Searching: {query}"
        )

        result: MatchResult
        try:
            result = search_one(
                page,
                query,
                min_score=min_score,
                debug=debug,
                expected_beer=expected_beer,
                expected_brewery=expected_brewery,
                expected_abv=expected_abv,
                expected_style=expected_style,
            )

        except Exception as e:
            result = {
                "query": query,
                "status": "failed",
                "reason": str(e),
            }

        if original:
            result[
                "original_menu_text"
            ] = original

        if isinstance(item, dict):
            result["input_brewery"] = expected_brewery or ""
            result["input_beer"] = expected_beer or ""
            result["input_abv"] = (
                "" if expected_abv is None else f"{expected_abv:g}"
            )
            result["input_style"] = expected_style or ""

        if result.get("status") == "rate_limited":
            result["batch_remaining"] = total - i
            results.append(result)
            if on_result is not None:
                on_result(result)
            if item_started is not None:
                _record_item_timing(
                    query,
                    perf_counter() - item_started,
                    matcher_seconds=get_last_matcher_timing_seconds(),
                )
            for remaining in items[i:]:
                skipped = unattempted_result(remaining, "Not searched because an earlier menu row hit HTTP 429. After the rate limit clears, use untap run --continue <run-folder>.")
                results.append(skipped)
                if on_result is not None:
                    on_result(skipped)
            break

        results.append(result)
        if on_result is not None:
            on_result(result)
        if item_started is not None:
            _record_item_timing(
                query,
                perf_counter() - item_started,
                matcher_seconds=get_last_matcher_timing_seconds(),
            )

    if batch_started is not None:
        _BATCH_TIMING_STATS["batch_seconds"] = perf_counter() - batch_started

    return results


class _TeeOutput:
    def __init__(self, terminal: TextIO, log: TextIO) -> None:
        self.terminal = terminal
        self.log = log

    def write(self, value: str) -> int:
        self.terminal.write(value)
        self.log.write(value)
        self.log.flush()
        return len(value)

    @property
    def encoding(self):
        return self.terminal.encoding

    def isatty(self) -> bool:
        return self.terminal.isatty()

    def fileno(self) -> int:
        return self.terminal.fileno()

    def flush(self) -> None:
        self.terminal.flush()
        self.log.flush()

@contextlib.contextmanager
def debug_transcript(run_directory: Path, enabled: bool) -> Iterator[None]:
    """Mirror batch debug output to an incrementally flushed run log."""
    if not enabled:
        yield
        return
    with (run_directory / "debug.txt").open("w", encoding="utf-8", newline="") as log:
        target: Any = _TeeOutput(sys.stdout, log)
        with contextlib.redirect_stdout(target):
            yield
