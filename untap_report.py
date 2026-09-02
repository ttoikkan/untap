"""Static HTML report rendering for completed Untap batch results.

This module is presentation-only. It consumes already completed MatchResult
records and writes a self-contained, responsive HTML file. It performs no
parsing, matching, browser automation, network requests, or CSV persistence.
"""

from datetime import date
from html import escape
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlparse

from untap_types import AlternativeRecord, MatchResult


DEFAULT_HTML_REPORT = "results.html"
DEFAULT_REPORT_TITLE = "Untap Results"


def _canonical_untappd_beer_url(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"untappd.com", "www.untappd.com"}:
        return None
    if not parsed.path.startswith("/b/"):
        return None
    return text


def _format_rating(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _format_count(value: Any) -> str:
    if value is None or value == "":
        return "N/A"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return escape(str(value))


def _format_abv(value: Any) -> str:
    if value is None or value == "":
        return "N/A"
    if isinstance(value, (int, float)):
        return f"{value:g}%"
    text = str(value).strip()
    return text if text.endswith("%") else f"{text}%"


def _style_group(type_name: Any) -> Optional[str]:
    """Derive one broad filter label from Untappd's canonical type_name.

    The vocabulary is entirely data-derived: Untap keeps the leading style
    component before Untappd's structural ``" - "`` subtype separator.
    Styles without that separator remain unchanged.
    """
    text = " ".join(str(type_name or "").split())
    if not text:
        return None
    group = text.split(" - ", 1)[0].strip()
    return group or text


def _style_group_key(type_name: Any) -> Optional[str]:
    group = _style_group(type_name)
    return group.casefold() if group else None


def _style_groups(results: Sequence[MatchResult]) -> List[str]:
    """Return report-present style groups in deterministic alphabetic order."""
    labels: Dict[str, str] = {}

    def remember(type_name: Any) -> None:
        group = _style_group(type_name)
        if not group:
            return
        key = group.casefold()
        current = labels.get(key)
        if current is None or group < current:
            labels[key] = group

    for result in results:
        if result.get("status") == "ok":
            remember(result.get("type_name"))
        else:
            for candidate in _review_candidates(result):
                remember(candidate.get("type_name"))

    return sorted(labels.values(), key=lambda value: (value.casefold(), value))


def _style_data_attribute(type_name: Any) -> str:
    key = _style_group_key(type_name)
    if not key:
        return ""
    return f' data-style-group="{escape(key, quote=True)}"'


def _linked_name(name: Any, url: Any) -> str:
    label = escape(str(name or "Unknown"))
    canonical = _canonical_untappd_beer_url(url)
    if not canonical:
        return label
    return (
        f'<a class="beer-link" href="{escape(canonical, quote=True)}" '
        f'target="_blank" rel="noopener noreferrer">{label}</a>'
    )


def _review_candidates(result: MatchResult) -> List[AlternativeRecord]:
    raw = result.get("same_abv_variants") or result.get("alternatives") or []
    candidates = list(raw)
    candidates.sort(
        key=lambda item: (
            -(float(item.get("score") or 0)),
            str(item.get("name") or "").casefold(),
        )
    )
    return candidates[:10]


def _rating_value(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _result_sort_rating(result: MatchResult) -> Optional[float]:
    """Return the rating used only to position one top-level report result."""
    if result.get("status") == "ok":
        return _rating_value(result.get("rating"))

    candidates = _review_candidates(result)
    if not candidates:
        return None
    return _rating_value(candidates[0].get("rating"))


def _sorted_report_results(results: Sequence[MatchResult]) -> List[MatchResult]:
    ordered = list(results)
    ordered.sort(
        key=lambda result: (
            _result_sort_rating(result) is not None,
            _result_sort_rating(result) or 0.0,
        ),
        reverse=True,
    )
    return ordered


def _meta_parts(parts: Iterable[Any]) -> str:
    visible = [escape(str(part)) for part in parts if part not in (None, "")]
    return " <span aria-hidden=\"true\">·</span> ".join(visible)


def render_html_report(
    results: Sequence[MatchResult],
    title: str = DEFAULT_REPORT_TITLE,
    report_date: Optional[str] = None,
) -> str:
    """Return one self-contained responsive HTML report."""
    clean_title = title.strip() or DEFAULT_REPORT_TITLE
    generated_date = report_date or date.today().isoformat()
    confirmed = [result for result in results if result.get("status") == "ok"]
    needs_review = [result for result in results if result.get("status") != "ok"]
    ordered_results = _sorted_report_results(results)
    style_groups = _style_groups(results)

    result_cards: List[str] = []
    for result in ordered_results:
        if result.get("status") == "ok":
            linked_name = _linked_name(result.get("beer"), result.get("url"))
            metadata = _meta_parts(
                [
                    result.get("brewery") or "Unknown brewery",
                    _format_abv(result.get("abv")),
                    result.get("type_name"),
                ]
            )
            result_cards.append(
            """
            <article class="beer-card"{style_attr}>
              <div class="rating-badge">{rating}</div>
              <div class="beer-content">
                <h3>{name}</h3>
                <p class="meta">{metadata}</p>
                <p class="ratings-count">{ratings} ratings</p>
              </div>
            </article>
            """.format(
                rating=_format_rating(result.get("rating")),
                name=linked_name,
                metadata=metadata,
                ratings=_format_count(result.get("ratings")),
                style_attr=_style_data_attribute(result.get("type_name")),
            )
            )
            continue

        status = str(result.get("status") or "unknown").replace("_", " ").title()
        query = escape(str(result.get("query") or result.get("input_beer") or "Untap result"))
        reason = escape(str(result.get("reason") or "Match is ambiguous"))
        candidate_cards: List[str] = []

        for candidate in _review_candidates(result):
            score = candidate.get("score")
            score_text = f"{float(score):.3f}" if score is not None else "N/A"
            candidate_cards.append(
                """
                <li class="candidate-card"{style_attr}>
                  <div class="candidate-score">Match {score}</div>
                  <div>
                    <h4>{name}</h4>
                    <p class="meta">{metadata}</p>
                    <p class="ratings-count">Rating {rating} · {ratings} ratings</p>
                  </div>
                </li>
                """.format(
                    score=score_text,
                    name=_linked_name(candidate.get("name"), candidate.get("url")),
                    metadata=_meta_parts(
                        [
                            candidate.get("brewery") or "Unknown brewery",
                            _format_abv(candidate.get("abv")),
                            candidate.get("type_name"),
                        ]
                    ),
                    rating=_format_rating(candidate.get("rating")),
                    ratings=_format_count(candidate.get("ratings")),
                    style_attr=_style_data_attribute(candidate.get("type_name")),
                )
            )

        if not candidate_cards and result.get("match"):
            candidate_cards.append(
                """
                <li class="candidate-card">
                  <div class="candidate-score">Best guess</div>
                  <div><h4>{name}</h4></div>
                </li>
                """.format(name=_linked_name(result.get("match"), result.get("url")))
            )

        candidates_html = "".join(candidate_cards) or '<p class="empty">No linked candidate was available.</p>'
        result_cards.append(
            """
            <article class="review-group">
              <div class="review-heading">
                <span class="status-pill">{status}</span>
                <h3>{query}</h3>
              </div>
              <p class="review-reason">{reason}</p>
              <ol class="candidate-list">{candidates}</ol>
            </article>
            """.format(status=escape(status), query=query, reason=reason, candidates=candidates_html)
        )

    results_html = "".join(result_cards) or '<p class="empty">No beers.</p>'

    filter_controls = []
    for index, group in enumerate(style_groups):
        key = group.casefold()
        filter_controls.append(
            '<label class="style-chip" for="style-filter-{index}">'
            '<input id="style-filter-{index}" type="checkbox" '
            'data-style-filter value="{key}" checked>'
            '<span>{label}</span></label>'.format(
                index=index,
                key=escape(key, quote=True),
                label=escape(group),
            )
        )
    style_filters_html = ""
    if filter_controls:
        style_filters_html = (
            '<fieldset class="style-filters"><legend>Styles</legend>'
            '<div class="style-chips">'
            + "".join(filter_controls)
            + '</div></fieldset>'
        )

    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="untap-report-title" content="{meta_title}">
  <meta name="untap-report-date" content="{report_date}">
  <meta name="untap-total-beers" content="{total}">
  <meta name="untap-confirmed-count" content="{confirmed_count}">
  <meta name="untap-review-count" content="{review_count}">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light dark; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: Canvas; color: CanvasText; }}
    main {{ width: min(900px, 100%); margin: 0 auto; padding: 24px 16px 48px; }}
    header {{ margin-bottom: 28px; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(1.8rem, 6vw, 2.5rem); }}
    h2 {{ margin-top: 32px; }}
    h3, h4, p {{ margin-top: 0; }}
    .summary {{ margin: 0; opacity: .72; }}
    .style-filters {{ margin: 22px 0 8px; padding: 14px 16px 16px; border: 1px solid color-mix(in srgb, CanvasText 16%, transparent); border-radius: 16px; }}
    .style-filters legend {{ padding: 0 7px; font-size: 1.08rem; font-weight: 700; }}
    .style-chips {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    .style-chip {{ position: relative; cursor: pointer; }}
    .style-chip input {{ position: absolute; width: 1px; height: 1px; margin: 0; opacity: 0; }}
    .style-chip span {{ display: inline-flex; align-items: center; min-height: 40px; padding: 0 16px; border: 1px solid color-mix(in srgb, CanvasText 28%, transparent); border-radius: 999px; background: color-mix(in srgb, Canvas 92%, CanvasText 8%); color: color-mix(in srgb, CanvasText 76%, Canvas 24%); font-weight: 600; transition: background-color 150ms, border-color 150ms, color 150ms, box-shadow 150ms; }}
    .style-chip span::before {{ content: "✓"; width: 0; margin-right: 0; overflow: hidden; color: LinkText; font-size: 1.08em; transition: width 150ms, margin-right 150ms; }}
    .style-chip input:checked + span {{ border-color: LinkText; background: color-mix(in srgb, Canvas 88%, LinkText 12%); color: CanvasText; }}
    .style-chip input:checked + span::before {{ width: 1em; margin-right: 8px; }}
    .style-chip:hover span {{ border-color: LinkText; }}
    .style-chip input:focus-visible + span {{ outline: 3px solid LinkText; outline-offset: 3px; }}
    [hidden] {{ display: none !important; }}
    .results-list, .candidate-list {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }}
    .beer-card, .candidate-card, .review-group {{ border: 1px solid color-mix(in srgb, CanvasText 16%, transparent); border-radius: 14px; background: color-mix(in srgb, Canvas 94%, CanvasText 6%); }}
    .beer-card {{ display: grid; grid-template-columns: 64px 1fr; gap: 14px; padding: 14px; align-items: start; }}
    .rating-badge {{ font-size: 1.35rem; font-weight: 750; font-variant-numeric: tabular-nums; }}
    .beer-content h3, .candidate-card h4 {{ margin-bottom: 5px; }}
    .beer-link {{ color: LinkText; text-decoration-thickness: .08em; text-underline-offset: .15em; }}
    .meta, .ratings-count, .review-reason {{ margin-bottom: 4px; opacity: .75; line-height: 1.4; }}
    .review-group {{ padding: 16px; }}
    .review-heading {{ display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }}
    .review-heading h3 {{ margin-bottom: 8px; }}
    .status-pill {{ border: 1px solid currentColor; border-radius: 999px; padding: 2px 8px; font-size: .78rem; font-weight: 700; opacity: .78; }}
    .candidate-list {{ margin-top: 12px; }}
    .candidate-card {{ display: grid; grid-template-columns: 92px 1fr; gap: 12px; padding: 12px; }}
    .candidate-score {{ font-weight: 700; font-variant-numeric: tabular-nums; }}
    .empty {{ opacity: .65; font-style: italic; }}
    @media (prefers-reduced-motion: reduce) {{
      .style-chip span, .style-chip span::before {{ transition: none; }}
    }}
    @media (max-width: 520px) {{
      main {{ padding: 18px 12px 36px; }}
      .beer-card {{ grid-template-columns: 54px 1fr; }}
      .candidate-card {{ grid-template-columns: 1fr; gap: 4px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{heading}</h1>
      <p class="summary">{total} beers · {confirmed_count} confirmed · {review_count} ambiguous</p>
    </header>

    {style_filters}

    <section aria-labelledby="results-heading">
      <h2 id="results-heading">Results</h2>
      <div class="results-list">{results_html}</div>
    </section>
  </main>
  <script>
    (function () {{
      const filters = Array.from(document.querySelectorAll('input[data-style-filter]'));
      if (!filters.length) return;

      const styledCards = Array.from(document.querySelectorAll('[data-style-group]'));
      const reviewGroups = Array.from(document.querySelectorAll('.review-group'));

      function applyStyleFilters() {{
        const enabled = new Set(
          filters.filter((filter) => filter.checked).map((filter) => filter.value)
        );

        styledCards.forEach((card) => {{
          card.hidden = !enabled.has(card.dataset.styleGroup);
        }});

        reviewGroups.forEach((group) => {{
          const candidates = Array.from(group.querySelectorAll('.candidate-card'));
          if (!candidates.length) return;
          group.hidden = candidates.every((candidate) => candidate.hidden);
        }});
      }}

      filters.forEach((filter) => filter.addEventListener('change', applyStyleFilters));
      applyStyleFilters();
    }})();
  </script>
</body>
</html>
""".format(
        title=escape(clean_title),
        meta_title=escape(clean_title, quote=True),
        heading=escape(clean_title),
        report_date=escape(generated_date, quote=True),
        total=len(results),
        confirmed_count=len(confirmed),
        review_count=len(needs_review),
        style_filters=style_filters_html,
        results_html=results_html,
    )


def save_html_report(
    results: Sequence[MatchResult],
    filename: str = DEFAULT_HTML_REPORT,
    title: str = DEFAULT_REPORT_TITLE,
) -> None:
    """Write a self-contained HTML report to ``filename``."""
    with open(filename, "w", encoding="utf-8", newline="") as handle:
        handle.write(render_html_report(results, title=title))
    print()
    print(f"Saved HTML report: {filename}")
