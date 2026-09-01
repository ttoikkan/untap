"""Untap command-line entry point and user-facing result presentation.

Raw menu validation happens before the browser context is opened. Runtime
responsibilities are delegated to the parser, matcher, transport, and batch
modules; this file intentionally remains the thin orchestration boundary.
"""

import sys
import re
import math
from untap_parser import (
    normalize,
    show_parsed_menu,
    supported_formats_help,
    read_validated_menu,
    menu_format_display_name,
    MenuValidationError,
)
from untap_matcher import (
    DEFAULT_MIN_SCORE,
    search_one,
    print_matcher_timing_summary,
    print_detail_algolia_parity_summary,
    print_algolia_confirmation_summary,
)
from untap_batch import (
    load_resume_csv,
    save_csv,
    read_queries_from_file,
    run_batch,
    reusable_resume_count,
    print_batch_timing_summary,
)
from untap_report import DEFAULT_HTML_REPORT, DEFAULT_REPORT_TITLE, save_html_report
from untap_untappd import (
    _reset_run_algolia_debug_stats,
    configure_search_timing,
    print_search_timing_summary,
    configure_search_transport_shadow,
    print_search_transport_shadow_summary,
    reset_search_transport_authority_state,
    print_search_transport_authority_summary,
    probe_algolia_sort,
    untappd_browser_page,
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

    failed = [
        r
        for r in results
        if r["status"] != "ok"
    ]

    print()

    print(
        f"{len(successful)} beers found"
    )

    print(
        f"{len(failed)} failed or uncertain"
    )

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
        for r in failed
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



def _print_cli_help():
    print("Usage:")
    print()
    print('  python3 untap.py "Badlands Fazy 2026"')
    print()
    print("  python3 untap.py --file beers.txt")
    print()
    print("  python3 untap.py --menu menu.txt")
    print()
    print("  python3 untap.py --menu menu.txt --csv results.csv")
    print("  python3 untap.py --menu menu.txt --html")
    print('  python3 untap.py --menu menu.txt --html --report-title "September Bottle Share"')
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
    print("  --resume")
    print("  --html")
    print("  --report-title TITLE")
    print("  --probe-abv-sort")
    print("  --smoke-test")


def main() -> None:
    args = sys.argv[1:]

    if not args:
        _print_cli_help()
        sys.exit(1)

    if any(arg in ("-h", "--help") for arg in args):
        _print_cli_help()
        return

    debug = False
    debug_timing = False
    shadow_search_transport_limit = 0
    show_queries = False
    formats_requested = False
    validate_menu_mode = None
    probe_abv_sort = False
    smoke_test_requested = False
    csv_filename = "results.csv"
    resume_requested = False
    html_requested = False
    report_title = None
    file_mode = None
    menu_mode = None
    min_score = DEFAULT_MIN_SCORE

    clean_args = []

    i = 0

    while i < len(args):
        arg = args[i]

        if arg == "--debug":
            debug = True
            i += 1

        elif arg == "--debug-timing":
            debug_timing = True
            i += 1

        elif arg == "--shadow-search-transport":
            if i + 1 >= len(args):
                print("--shadow-search-transport requires a positive integer limit")
                sys.exit(1)
            try:
                shadow_search_transport_limit = int(args[i + 1])
            except ValueError:
                print("--shadow-search-transport requires a positive integer limit")
                sys.exit(1)
            if shadow_search_transport_limit <= 0:
                print("--shadow-search-transport requires a positive integer limit")
                sys.exit(1)
            debug_timing = True
            i += 2

        elif arg == "--show-queries":
            show_queries = True
            i += 1

        elif arg in ("--formats", "--help-formats"):
            formats_requested = True
            i += 1

        elif arg == "--validate-menu":
            if i + 1 >= len(args):
                print("--validate-menu requires a filename")
                sys.exit(1)
            validate_menu_mode = args[i + 1]
            i += 2

        elif arg == "--probe-abv-sort":
            probe_abv_sort = True
            i += 1

        elif arg == "--smoke-test":
            smoke_test_requested = True
            i += 1

        elif arg == "--file":
            if i + 1 >= len(args):
                print(
                    "--file requires "
                    "a filename"
                )
                sys.exit(1)

            file_mode = args[i + 1]
            i += 2

        elif arg == "--menu":
            if i + 1 >= len(args):
                print(
                    "--menu requires "
                    "a filename"
                )
                sys.exit(1)

            menu_mode = args[i + 1]
            i += 2

        elif arg == "--csv":
            if i + 1 >= len(args):
                print(
                    "--csv requires "
                    "a filename"
                )
                sys.exit(1)

            csv_filename = args[i + 1]
            i += 2

        elif arg == "--resume":
            resume_requested = True
            i += 1

        elif arg == "--html":
            html_requested = True
            i += 1

        elif arg == "--report-title":
            if i + 1 >= len(args):
                print("--report-title requires a non-empty title")
                sys.exit(1)
            report_title = args[i + 1].strip()
            if not report_title:
                print("--report-title requires a non-empty title")
                sys.exit(1)
            i += 2

        elif arg == "--min-score":
            if i + 1 >= len(args):
                print(
                    "--min-score requires "
                    "a number"
                )
                sys.exit(1)

            try:
                min_score = float(
                    args[i + 1]
                )
            except ValueError:
                print(
                    f"--min-score expects a number, "
                    f"got {args[i + 1]!r}"
                )
                sys.exit(1)

            if (
                not math.isfinite(min_score)
                or not (0.0 <= min_score <= 1.0)
            ):
                print(
                    "--min-score must be a finite number "
                    "between 0.0 and 1.0"
                )
                sys.exit(1)

            i += 2

        else:
            clean_args.append(arg)
            i += 1

    if formats_requested:
        print(supported_formats_help())
        if not (clean_args or file_mode or menu_mode or validate_menu_mode or probe_abv_sort or smoke_test_requested or html_requested or report_title):
            return

    if report_title is not None and not html_requested:
        print("--report-title requires --html")
        sys.exit(1)

    if validate_menu_mode and (file_mode or menu_mode or clean_args or probe_abv_sort or smoke_test_requested or html_requested):
        print("--validate-menu is a local-only command and cannot be combined with search input")
        sys.exit(1)

    if smoke_test_requested and (file_mode or menu_mode or clean_args or validate_menu_mode or probe_abv_sort or resume_requested or html_requested):
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

    if resume_requested and not menu_mode:
        print("--resume currently requires --menu so rows can be matched safely")
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
            from untap_smoke import run_live_smoke_test

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

            resume_rows = None
            if resume_requested:
                try:
                    resume_rows = load_resume_csv(csv_filename)
                except OSError as e:
                    print(
                        f"Could not read resume CSV "
                        f"'{csv_filename}': {e}"
                    )
                    sys.exit(1)
                except ValueError as e:
                    print(f"Could not use resume CSV: {e}")
                    sys.exit(1)

                reusable = reusable_resume_count(resume_rows)
                print(
                    f"Resume: {reusable} previously confirmed "
                    f"row{'s' if reusable != 1 else ''} available "
                    f"from {csv_filename}"
                )

            results = run_batch(
                page,
                items,
                min_score=min_score,
                debug=debug,
                resume_rows=resume_rows,
            )

            print_search_timing_summary()
            print_search_transport_authority_summary()
            print_search_transport_shadow_summary()
            print_matcher_timing_summary()
            print_detail_algolia_parity_summary()
            print_algolia_confirmation_summary()
            print_batch_timing_summary()

            print_batch_results(
                results
            )

            if csv_filename:
                save_csv(
                    results,
                    csv_filename,
                )

            if html_requested:
                save_html_report(results, DEFAULT_HTML_REPORT, title=report_title or DEFAULT_REPORT_TITLE)

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

            results = run_batch(
                page,
                queries,
                min_score=min_score,
                debug=debug,
            )

            print_search_timing_summary()
            print_search_transport_authority_summary()
            print_search_transport_shadow_summary()
            print_matcher_timing_summary()
            print_detail_algolia_parity_summary()
            print_algolia_confirmation_summary()
            print_batch_timing_summary()

            print_batch_results(
                results
            )

            if csv_filename:
                save_csv(
                    results,
                    csv_filename,
                )

            if html_requested:
                save_html_report(results, DEFAULT_HTML_REPORT, title=report_title or DEFAULT_REPORT_TITLE)

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
