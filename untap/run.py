"""Untap command-line entry point and user-facing result presentation.

Raw menu validation happens before the browser context is opened. Runtime
responsibilities are delegated to the parser, matcher, transport, and batch
modules; this file intentionally remains the thin orchestration boundary.
"""

import sys
import argparse
import json
import os
import re
import math
from typing import Optional, Sequence
from datetime import datetime
from pathlib import Path
from untap.version import __version__
from untap.parser import (
    normalize,
    show_parsed_menu,
    supported_formats_help,
    read_validated_menu,
    menu_format_display_name,
    MenuValidationError,
)
from untap.matcher import (
    DEFAULT_MIN_SCORE,
    search_one,
    print_matcher_timing_summary,
    print_detail_algolia_parity_summary,
    print_algolia_confirmation_summary,
)
from untap.batch import (
    read_queries_from_file,
    run_batch,
    unattempted_result,
    debug_transcript,
    print_batch_timing_summary,
)
from untap.report import DEFAULT_HTML_REPORT, DEFAULT_REPORT_TITLE
# Intentional compatibility export: historical callers use run.save_csv.
from untap.run_output import write_run_outputs, save_csv as save_csv
from untap.snapshot import build_snapshot, save_snapshot
from untap.registry import register_run_safely
from untap.transport import (
    _reset_run_algolia_debug_stats,
    configure_search_timing,
    print_search_timing_summary,
    configure_search_transport_shadow,
    print_search_transport_shadow_summary,
    reset_search_transport_authority_state,
    print_search_transport_authority_summary,
    probe_algolia_sort,
    untappd_browser_page,
    BrowserUnavailableError,
)



def _strip_leading_article_words(words):
    while words and words[0] in {"the", "a", "an"}:
        words = words[1:]
    return words


def ambiguity_family_candidates(result):
    """
    Choose the most relevant candidate family for ambiguity presentation
    without discarding the broader alternatives stored in the result.

    Priority:
      1. Exact same-ABV family variants already identified by the matcher.
      2. A conservative release/version family derived from the menu query
         and candidate names, e.g.:
           Executioner -> The Executioner / The Executioner 2024 / ...
         while excluding names that add a leading modifier such as:
           Baby Executioner 2026
      3. Fall back to the general alternatives list.
    """
    same_abv = result.get("same_abv_variants") or []
    if same_abv:
        return same_abv, "same_abv"

    alternatives = result.get("alternatives") or []
    if len(alternatives) < 2:
        return alternatives, "alternatives"

    query_words = [
        word
        for word in normalize(result.get("query") or "").split()
        if word
    ]

    if not query_words:
        return alternatives, "alternatives"

    # Try suffixes of the query because raw --file input often contains the
    # brewery followed by the beer name (e.g. "Factory Executioner").
    # Prefer the longest suffix that identifies at least two candidates.
    family_norm = None

    for start_idx in range(len(query_words)):
        suffix_words = query_words[start_idx:]
        if not suffix_words:
            continue

        suffix = " ".join(suffix_words)

        matching = []
        for item in alternatives:
            candidate_words = normalize(item.get("name") or "").split()
            candidate_words = _strip_leading_article_words(candidate_words)

            if not candidate_words:
                continue

            candidate_norm = " ".join(candidate_words)

            if (
                candidate_norm == suffix
                or candidate_norm.startswith(suffix + " ")
            ):
                matching.append(item)

        if len(matching) >= 2:
            family_norm = suffix
            break

    if not family_norm:
        return alternatives, "alternatives"

    family = []
    seen = set()

    for item in alternatives:
        candidate_words = normalize(item.get("name") or "").split()
        candidate_words = _strip_leading_article_words(candidate_words)
        candidate_norm = " ".join(candidate_words)

        if not (
            candidate_norm == family_norm
            or candidate_norm.startswith(family_norm + " ")
        ):
            continue

        key = (
            candidate_norm,
            item.get("url"),
        )

        if key in seen:
            continue
        seen.add(key)
        family.append(item)

    if len(family) < 2:
        return alternatives, "alternatives"

    family.sort(
        key=lambda item: (
            -(item.get("score") or 0),
            normalize(item.get("name") or ""),
        )
    )

    return family, "family"


def ambiguity_display_reason(result, displayed_candidates, family_kind):
    """
    Give a more useful display reason when a release/version family was
    identified, without changing the underlying ambiguity decision.
    """
    if family_kind == "same_abv":
        return result.get("reason") or "multiple same-ABV variants found"

    if family_kind != "family" or len(displayed_candidates) < 2:
        return result.get("reason") or "ambiguous match"

    names = [
        (item.get("name") or "").strip()
        for item in displayed_candidates
        if (item.get("name") or "").strip()
    ]

    if not names:
        return result.get("reason") or "ambiguous match"

    base_words = normalize(names[0]).split()
    base_words = _strip_leading_article_words(base_words)

    # Remove a trailing year/version-like token from the first candidate when
    # deriving a concise family label.
    if base_words and re.fullmatch(r"\d{4}", base_words[-1]):
        base_words = base_words[:-1]

    family_label = " ".join(base_words).strip()

    if family_label:
        return f"multiple {family_label.title()} releases found"

    return result.get("reason") or "ambiguous match"


# ============================================================
# Output
# ============================================================

def format_rating(value):
    if value is None:
        return "N/A"

    return f"{value:.2f}"


def format_ratings_count(value):
    if value is None:
        return "N/A"

    return f"{value:,}"


def print_single_result(result):
    if result["status"] == "rate_limited":
        print("Rate limited")
        print("------------")
        print(result.get("reason") or "Untappd rate limited the search (HTTP 429)")
        print("No beer match decision was made. Try again later.")
        return

    if result["status"] == "failed":
        print(
            f"Failed: "
            f"{result['reason']}"
        )
        return

    if result["status"] == "ambiguous":
        print(
            "Ambiguous match"
        )
        print(
            "---------------"
        )
        print(
            f"Search: "
            f"{result['query']}"
        )
        print(
            f"Best candidate: "
            f"{result['match']}"
        )
        print(
            f"Score:  "
            f"{result['score']:.3f}"
        )
        print(
            f"Reason: "
            f"{result['reason']}"
        )

        same_abv_variants = result.get("same_abv_variants") or []

        if same_abv_variants:
            print()
            print("Same-ABV variants:")

            for item in same_abv_variants:
                abv = (
                    f"{item['abv']:g}%"
                    if item.get("abv") is not None
                    else "ABV N/A"
                )
                print(f"  - {item['name']} ({abv})")

        alternatives = result.get("alternatives") or []

        if alternatives and not same_abv_variants:
            print()
            print("Plausible candidates:")

            for item in alternatives:
                abv = (
                    f"{item['abv']:g}%"
                    if item.get("abv") is not None
                    else "ABV N/A"
                )

                print(
                    f"  - {item['name']} "
                    f"(score {item['score']:.3f}, {abv})"
                )

        return

    if result["status"] == "low_confidence":
        print(
            "Low-confidence match"
        )
        print(
            "--------------------"
        )
        print(
            f"Search: "
            f"{result['query']}"
        )
        print(
            f"Found:  "
            f"{result['match']}"
        )
        print(
            f"Score:  "
            f"{result['score']:.3f}"
        )
        if result.get("reason"):
            print(
                f"Reason: "
                f"{result['reason']}"
            )
        print(
            f"URL:    "
            f"{result['url']}"
        )
        return

    print("Best match:")
    print(result["search_text"])

    print(
        f"Match score: "
        f"{result['score']:.3f}"
    )

    print()
    print("Result")
    print("------")

    print(
        f"Beer:    "
        f"{result['beer']}"
    )

    print(
        f"Brewery: "
        f"{result['brewery']}"
    )

    print(
        f"Rating:  "
        f"{format_rating(result['rating'])}"
    )

    print(
        f"Ratings: "
        f"{format_ratings_count(result['ratings'])}"
    )

    print(
        f"ABV:     "
        f"{result['abv'] or 'Not found'}"
    )

    print(
        f"IBU:     "
        f"{result['ibu'] or 'Not found'}"
    )

    print(
        f"URL:     "
        f"{result['url']}"
    )


def print_batch_results(results):
    successful = [
        r
        for r in results
        if r["status"] == "ok"
    ]

    successful.sort(
        key=lambda r: (
            r["rating"] is not None,
            r["rating"] or 0,
        ),
        reverse=True,
    )

    print()
    print("Untappd results")
    print("=" * 104)

    print(
        f"{'Rating':>6}  "
        f"{'Ratings':>8}  "
        f"{'ABV':>6}  "
        f"{'Beer':<40}  "
        f"{'Brewery'}"
    )

    print(
        f"{'-' * 6}  "
        f"{'-' * 8}  "
        f"{'-' * 6}  "
        f"{'-' * 40}  "
        f"{'-' * 28}"
    )

    for r in successful:
        rating = format_rating(
            r["rating"]
        )

        ratings = (
            str(r["ratings"])
            if r["ratings"] is not None
            else "N/A"
        )

        abv = (
            r["abv"]
            or "N/A"
        )

        beer = r["beer"][:40]
        brewery = r["brewery"]

        print(
            f"{rating:>6}  "
            f"{ratings:>8}  "
            f"{abv:>6}  "
            f"{beer:<40}  "
            f"{brewery}"
        )

    ambiguous = [
        r
        for r in results
        if r["status"] == "ambiguous"
    ]

    if ambiguous:
        print()
        print("Ambiguous results")
        print("=" * 113)

        for group_index, r in enumerate(ambiguous):
            if group_index:
                print()

            displayed_candidates, family_kind = ambiguity_family_candidates(r)
            display_reason = ambiguity_display_reason(
                r,
                displayed_candidates,
                family_kind,
            )

            print(
                f"{r['query']}: "
                f"ambiguous — {display_reason}"
            )
            if r.get("search_warning"):
                print(r["search_warning"])

            print(
                f"{'Rating':>6}  "
                f"{'Ratings':>8}  "
                f"{'ABV':>6}  "
                f"{'Beer':<40}  "
                f"{'Brewery':<28}  "
                f"{'Score':>5}"
            )

            print(
                f"{'-' * 6}  "
                f"{'-' * 8}  "
                f"{'-' * 6}  "
                f"{'-' * 40}  "
                f"{'-' * 28}  "
                f"{'-' * 5}"
            )

            for item in displayed_candidates[:10]:
                rating = format_rating(
                    item.get("rating")
                )

                ratings = (
                    str(item["ratings"])
                    if item.get("ratings") is not None
                    else "N/A"
                )

                abv = (
                    f"{item['abv']:g}%"
                    if item.get("abv") is not None
                    else "N/A"
                )

                beer = (
                    item.get("name")
                    or "Unknown"
                )[:40]

                brewery = (
                    item.get("brewery")
                    or "Unknown"
                )[:28]

                score = item.get("score")
                score_text = (
                    f"{score:.3f}"
                    if score is not None
                    else "N/A"
                )

                print(
                    f"{rating:>6}  "
                    f"{ratings:>8}  "
                    f"{abv:>6}  "
                    f"{beer:<40}  "
                    f"{brewery:<28}  "
                    f"{score_text:>5}"
                )

    unresolved = [
        r
        for r in results
        if r["status"] != "ok"
    ]

    print()

    failed_count = sum(r["status"] == "failed" for r in results)
    other_count = len(unresolved) - len(ambiguous) - failed_count
    summary = (f"{len(results)} beers · {len(successful)} confirmed · "
               f"{len(ambiguous)} ambiguous · {failed_count} failed")
    if other_count:
        summary += f" · {other_count} other unresolved"
    print(summary)

    rate_limited = next(
        (r for r in results if r.get("status") == "rate_limited"),
        None,
    )

    if rate_limited:
        remaining = rate_limited.get("batch_remaining", 0)
        print()
        print("Batch stopped early because Untappd rate limited requests (HTTP 429).")
        if remaining:
            print(
                f"{remaining} remaining search"
                f"{'es' if remaining != 1 else ''} were not attempted."
            )

    problems = [
        r
        for r in unresolved
        if r["status"] != "ambiguous"
    ]

    if problems:
        print()
        print("Problems")
        print("--------")

        for r in problems:
            if r["status"] == "rate_limited":
                print(
                    f"{r['query']}: "
                    f"{r.get('reason') or 'rate limited (HTTP 429)'}"
                )
            elif (
                r["status"]
                == "low_confidence"
            ):
                print(
                    f"{r['query']}: "
                    f"low-confidence match "
                    f"'{r['match']}' "
                    f"(score "
                    f"{r['score']:.3f})"
                    + (
                        f" — {r['reason']}"
                        if r.get("reason")
                        else ""
                    )
                )
            else:
                print(
                    f"{r['query']}: "
                    f"{r['reason']}"
                )



def create_run_directory(input_filename: str, title: Optional[str]) -> Path:
    """Reserve a unique output directory, including concurrent same-second runs."""
    label = title or Path(input_filename).stem
    slug = re.sub(r"[^\w-]+", "-", label.lower())
    slug = re.sub(r"-+", "-", slug).strip("-_")[:100].rstrip("-_") or "run"
    root = Path("results")
    root.mkdir(exist_ok=True)
    name = f"{datetime.now():%Y-%m-%d_%H%M%S}_{slug}"
    suffix = 0
    while True:
        destination = root / (name if not suffix else f"{name}-{suffix}")
        try:
            destination.mkdir()
            return destination.resolve()
        except FileExistsError:
            suffix += 1






def _run_and_save_batch(page, items, run_directory: Path, *, min_score: float,
                        debug: bool,
                        report_title: Optional[str], csv_requested: bool = False) -> None:
    results = []
    completed = False
    save_snapshot(build_snapshot([unattempted_result(item, "Search has not completed") for item in items], report_title or DEFAULT_REPORT_TITLE), run_directory / "results.input.json")
    with debug_transcript(run_directory, debug), (run_directory / "results.partial.jsonl").open("x", encoding="utf-8") as journal:
        def checkpoint(result):
            journal.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
            results.append(result)

        try:
            returned = run_batch(page, items, min_score=min_score, debug=debug, on_result=checkpoint)
            # Keep compatibility with callers replacing run_batch in offline tests.
            if not results:
                results.extend(returned)
            completed = True
        finally:
            if not completed:
                for item in items[len(results):]:
                    results.append(unattempted_result(item, f"Batch interrupted before this row completed. Use untap run --continue {run_directory} to search the remaining rows."))
            snapshot = build_snapshot(results, report_title or DEFAULT_REPORT_TITLE)
            write_run_outputs(snapshot, run_directory, csv_requested=csv_requested,
                              csv_first=True, use_snapshot_date=False)
            print()
            print(f"Saved HTML report: {run_directory / DEFAULT_HTML_REPORT}")
            if completed and not any(result.get("status") in ("rate_limited", "not_attempted") for result in results):
                (run_directory / "results.partial.jsonl").unlink(missing_ok=True)
                (run_directory / "results.input.json").unlink(missing_ok=True)
            print(f"Run outputs: {run_directory}")
            if not completed:
                print("Batch interrupted: completed results were saved; remaining rows are marked not attempted.")
        print_search_timing_summary()
        print_search_transport_authority_summary()
        print_search_transport_shadow_summary()
        print_matcher_timing_summary()
        print_detail_algolia_parity_summary()
        print_algolia_confirmation_summary()
        print_batch_timing_summary()
        print_batch_results(results)


def _print_cli_help():
    print("Usage:")
    print()
    print('  python3 untap.py "Badlands Fazy 2026"')
    print()
    print("  python3 untap.py --file beers.txt")
    print()
    print("  python3 untap.py --menu menu.txt")
    print("  python3 untap.py --continue results/<unfinished-run>/")
    print()
    print("  --csv additionally exports results.csv for spreadsheet use.")
    print("  HTML and JSON are saved by default.")
    print("  Batch outputs are saved in a unique results/<timestamp>_<menu>/ folder.")
    print("  python3 untap.py --menu menu.txt --csv")
    print('  python3 untap.py --menu menu.txt --report-title "September Bottle Share"')
    print()
    print("Options:")
    print("  -h, --help")
    print("  --debug")
    print("  --debug-timing")
    print("  --shadow-search-transport N")
    print("  --min-score 0.75")
    print("  --show-queries")
    print("  --formats / --help-formats")
    print("  --validate-menu menu.txt")
    print("  --csv")
    print("  --html (accepted for compatibility; HTML is saved by default)")
    print("  --report-title TITLE")
    print("  --probe-abv-sort")
    print("  --smoke-test")


def _score_argument(value: str) -> float:
    try:
        score = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a number") from exc
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise argparse.ArgumentTypeError("must be a finite number between 0.0 and 1.0")
    return score


def _positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a positive integer limit") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer limit")
    return number


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--version", action="version", version=f"untap {__version__}")
    parser.add_argument("query", nargs="*", help="single-beer search text")
    parser.add_argument("--recovery-menu", metavar="FILE", help="original TSV for recovery of a v103 journal without a manifest")
    parser.add_argument("--continue", dest="continue_source", metavar="RUN", help="continue only rate-limited or unattempted rows into a new run")
    parser.add_argument("--menu", metavar="FILE", help="brewery, beer, ABV, style TSV menu")
    parser.add_argument("--file", metavar="FILE", help="one search query per line")
    parser.add_argument("--validate-menu", metavar="FILE", help="validate TSV locally without searching")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--debug-timing", action="store_true")
    parser.add_argument("--shadow-search-transport", type=_positive_integer, default=0, metavar="N",
                        help="compare up to N successful UI captures with a diagnostic replay; HTTP 429 stops the run")
    parser.add_argument("--show-queries", action="store_true")
    parser.add_argument("--formats", "--help-formats", action="store_true")
    parser.add_argument("--probe-abv-sort", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--html", action="store_true", help="compatibility flag; HTML is saved by default")
    parser.add_argument("--csv", action="store_true", help="also export results.csv in the run folder; takes no filename")
    parser.add_argument("--report-title", metavar="TITLE")
    parser.add_argument("--register-refresh", metavar="CONFIG")
    parser.add_argument("--min-score", type=_score_argument, default=DEFAULT_MIN_SCORE)


def _build_cli_parser(prog: Optional[str] = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Search Untappd from a query or a four-column TSV menu.",
        allow_abbrev=False,
    )
    configure_parser(parser)
    return parser


def _parse_cli_args(args, parser=None):
    parser = parser if parser is not None else _build_cli_parser()
    options = parser.parse_intermixed_args(args)
    if options.recovery_menu and not options.continue_source:
        parser.error("--recovery-menu requires --continue")
    if options.continue_source and (options.query or options.menu or options.file or options.validate_menu or options.smoke_test or options.probe_abv_sort or options.formats or options.register_refresh or options.report_title):
        parser.error("--continue takes a saved run and cannot be combined with new input, title, validation or registration options")
    if options.query and (options.menu or options.file or options.validate_menu):
        parser.error("positional search text cannot accompany --menu, --file or --validate-menu; --csv takes no filename")
    if options.menu and options.file:
        parser.error("use either --menu or --file, not both")
    if options.report_title is not None:
        options.report_title = options.report_title.strip()
        if not options.report_title:
            parser.error("--report-title requires a non-empty title")
    return options


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = list(argv) if argv is not None else sys.argv[1:]
    if not args:
        _print_cli_help()
        sys.exit(1)
    options = _parse_cli_args(args)
    run_options(options)


def run_options(options: argparse.Namespace) -> None:
    try:
        _run_options(options)
    except BrowserUnavailableError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None


def _run_options(options: argparse.Namespace) -> None:
    if options.continue_source:
        from untap.continue_run import continue_run
        configure_search_timing(options.debug_timing or bool(options.shadow_search_transport))
        configure_search_transport_shadow(options.shadow_search_transport)
        reset_search_transport_authority_state()
        try:
            output = continue_run(Path(options.continue_source), min_score=options.min_score,
                                  debug=options.debug, csv_requested=options.csv,
                                  recovery_menu=Path(options.recovery_menu) if options.recovery_menu else None)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            print(f"Could not continue run: {exc}")
            sys.exit(1)
        print(f"Continued run: {output}")
        return
    debug = options.debug
    debug_timing = options.debug_timing or bool(options.shadow_search_transport)
    shadow_search_transport_limit = options.shadow_search_transport
    show_queries = options.show_queries
    formats_requested = options.formats
    validate_menu_mode = options.validate_menu
    probe_abv_sort = options.probe_abv_sort
    smoke_test_requested = options.smoke_test
    html_requested = options.html
    csv_requested = options.csv
    report_title = options.report_title
    register_refresh = options.register_refresh
    file_mode = options.file
    menu_mode = options.menu
    min_score = options.min_score
    clean_args = options.query

    if formats_requested:
        print(supported_formats_help())
        if not (clean_args or file_mode or menu_mode or validate_menu_mode or probe_abv_sort or smoke_test_requested or html_requested or report_title or csv_requested):
            return

    if csv_requested and (not (file_mode or menu_mode) or validate_menu_mode or smoke_test_requested or probe_abv_sort):
        print("--csv requires --menu or --file batch input")
        sys.exit(1)

    if register_refresh and (not (file_mode or menu_mode) or not report_title):
        print("--register-refresh requires batch input and --report-title")
        sys.exit(1)

    if report_title is not None and not (file_mode or menu_mode):
        print("--report-title requires --menu or --file batch input")
        sys.exit(1)

    if validate_menu_mode and (file_mode or menu_mode or clean_args or probe_abv_sort or smoke_test_requested or html_requested):
        print("--validate-menu is a local-only command and cannot be combined with search input")
        sys.exit(1)

    if smoke_test_requested and (file_mode or menu_mode or clean_args or validate_menu_mode or probe_abv_sort or html_requested):
        print("--smoke-test is a standalone live integration check and cannot be combined with search input")
        sys.exit(1)

    if html_requested and not (file_mode or menu_mode):
        print("--html requires --menu or --file batch input")
        sys.exit(1)

    if html_requested and probe_abv_sort:
        print("--html cannot be combined with --probe-abv-sort")
        sys.exit(1)

    if validate_menu_mode:
        try:
            detected_format, items = read_validated_menu(validate_menu_mode)
        except OSError as e:
            print(f"Could not read menu file '{validate_menu_mode}': {e}")
            sys.exit(1)
        except MenuValidationError as e:
            print("Menu validation failed.")
            print()
            print(str(e))
            print()
            print(supported_formats_help())
            print("No Untappd queries were made.")
            sys.exit(1)

        print("Menu validation succeeded.")
        print(f"Detected menu format: {menu_format_display_name(detected_format)}")
        print(f"Normalized records: {len(items)}")
        if show_queries:
            show_parsed_menu(items)
        print("No Untappd queries were made.")
        return

    # Raw menu files are fully validated and normalized before Playwright is
    # imported or Chromium is started. This is the v56 preflight boundary.
    preflight_menu_items = None
    preflight_menu_format = None
    if menu_mode:
        try:
            preflight_menu_format, preflight_menu_items = read_validated_menu(menu_mode)
        except OSError as e:
            print(f"Could not read menu file '{menu_mode}': {e}")
            sys.exit(1)
        except MenuValidationError as e:
            print("Menu validation failed.")
            print()
            print(str(e))
            print()
            print(supported_formats_help())
            print("No Untappd queries were made.")
            sys.exit(1)

        if show_queries:
            print(f"Detected menu format: {menu_format_display_name(preflight_menu_format)}")
            show_parsed_menu(preflight_menu_items)

    if probe_abv_sort and (file_mode or menu_mode):
        print("--probe-abv-sort is for a single query, not --file/--menu")
        sys.exit(1)

    if file_mode and menu_mode:
        print(
            "Use either --file or --menu, "
            "not both."
        )
        sys.exit(1)

    # Timing diagnostics are opt-in and transport-only. Enabling them does not
    # alter query selection, matching policy, or request strategy.
    configure_search_timing(debug_timing)
    configure_search_transport_shadow(shadow_search_transport_limit)
    reset_search_transport_authority_state()

    # Browser automation is opened only after all local menu preflight checks pass.
    with untappd_browser_page() as page:
        if smoke_test_requested:
            from untap.smoke import run_live_smoke_test

            smoke_exit_code = run_live_smoke_test(page)
            if debug_timing:
                print_search_timing_summary()
                print_search_transport_authority_summary()
                print_matcher_timing_summary()
                print_algolia_confirmation_summary()
            if smoke_exit_code != 0:
                sys.exit(smoke_exit_code)
            return

        # ----------------------------------------------------
        # Raw menu mode
        # ----------------------------------------------------

        if menu_mode:
            if preflight_menu_items is None:
                raise RuntimeError("validated menu items unexpectedly unavailable after preflight")
            items = preflight_menu_items

            run_directory = create_run_directory(menu_mode, report_title)

            _run_and_save_batch(
                page, items, run_directory, min_score=min_score, debug=debug,
                report_title=report_title, csv_requested=csv_requested,
            )
            if register_refresh:
                register_run_safely(register_refresh, run_directory)

        # ----------------------------------------------------
        # One-query-per-line mode
        # ----------------------------------------------------

        elif file_mode:
            try:
                queries = (
                    read_queries_from_file(
                        file_mode
                    )
                )
            except OSError as e:
                print(
                    f"Could not read file "
                    f"'{file_mode}': {e}"
                )
                sys.exit(1)

            run_directory = create_run_directory(file_mode, report_title)
            _run_and_save_batch(
                page, queries, run_directory, min_score=min_score, debug=debug,
                report_title=report_title, csv_requested=csv_requested,
            )
            if register_refresh:
                register_run_safely(register_refresh, run_directory)

        # ----------------------------------------------------
        # Single beer mode
        # ----------------------------------------------------

        else:
            query = " ".join(
                clean_args
            )

            if probe_abv_sort:
                if not query.strip():
                    print("--probe-abv-sort requires a single search query")
                    sys.exit(1)
                probe_algolia_sort(page, query)
                return

            print(
                f'Searching Untappd for '
                f'"{query}"...\n'
            )

            _reset_run_algolia_debug_stats()

            result = search_one(
                page,
                query,
                min_score=min_score,
                debug=debug,
            )

            print_search_timing_summary()
            print_search_transport_shadow_summary()

            print_single_result(
                result
            )


if __name__ == "__main__":
    main()
