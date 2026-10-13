"""Static HTML report rendering for completed Untap batch results.

This module is presentation-only. It consumes already completed MatchResult
records and writes a self-contained, responsive HTML file. It performs no
parsing, matching, browser automation, network requests, or CSV persistence.
"""

from datetime import date
from html import escape
from importlib.resources import files
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlparse

from untap.types import MatchResult
from untap.report_model import (prepare_report_rows, format_rating as _format_rating,
                                format_count, format_abv as _format_abv, production_label)
# Compatibility names remain available to callers of older source versions.
from untap.review_policy import (
    DEFAULT_REPORT_TITLE as DEFAULT_REPORT_TITLE,
    selection_report_id as selection_report_id,
    review_candidates as _review_candidates,
    sorted_review_results as _sorted_report_results,
    result_sort_rating as _result_sort_rating,
)


__all__ = [
    # Public API.
    "DEFAULT_HTML_REPORT",
    "DEFAULT_REPORT_TITLE",
    "render_html_report",
    "save_html_report",
    "selection_report_id",
    # Compatibility names, kept intentionally for callers of older source versions.
    "_format_abv",
    "_format_rating",
    "_result_sort_rating",
    "_review_candidates",
    "_sorted_report_results",
]

DEFAULT_HTML_REPORT = "results.html"


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


def _format_count(value: Any) -> str:
    return escape(format_count(value))


def _untappd_asset_url(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme != "https" or parsed.netloc.lower() != "assets.untappd.com":
        return None
    return text


def _label_image(value: Any, hd_value: Any, name: Any) -> str:
    """Render a thumbnail and an optional keyboard-accessible HD control."""
    text = _untappd_asset_url(value)
    if not text:
        return ""
    alt = escape(f"{name or 'Beer'} label", quote=True)
    image = ('<img class="beer-label" src="{src}" alt="{alt}" loading="lazy" '
             'decoding="async" referrerpolicy="no-referrer" onerror="this.hidden=true">').format(
                 src=escape(text, quote=True), alt=alt)
    hd_text = _untappd_asset_url(hd_value)
    if not hd_text:
        return image
    return ('<button class="label-preview-button" type="button" data-label-preview="{hd}" '
            'aria-label="View larger {alt}">{image}</button>').format(
                hd=escape(hd_text, quote=True), alt=alt, image=image)


def _production_html(text: Optional[str]) -> str:
    if text is None:
        return '<p class="production-status production-status-empty" aria-hidden="true">&nbsp;</p>'
    return f'<p class="production-status">{text}</p>'


def _production_status(value: Any) -> str:
    """Render explicit production metadata or a height-preserving empty row."""
    text = production_label(value)
    if text is None:
        return '<p class="production-status production-status-empty" aria-hidden="true">&nbsp;</p>'
    return f'<p class="production-status">{text}</p>'


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


def _meta_parts(parts: Iterable[Any]) -> str:
    visible = [escape(str(part)) for part in parts if part not in (None, "")]
    return " <span aria-hidden=\"true\">·</span> ".join(visible)


def _render_result_cards(results: Sequence[MatchResult]) -> str:
    """Render ordered beer/review cards using occurrence-aware input IDs."""
    result_cards: List[str] = []
    for row in prepare_report_rows(results):
        if row.confirmed is not None:
            beer = row.confirmed
            image = _label_image(beer.image_url, beer.image_hd_url, beer.name)
            production_status = _production_html(beer.production)
            linked_name = _linked_name(beer.name, beer.url)
            metadata = _meta_parts([beer.abv, beer.type_name])
            result_cards.append(
            """
            <article class="beer-card{image_class}" data-status="ok"{style_attr}>
              {image}
              <div class="rating-column"><div class="rating-badge">{rating}</div>
                <p class="ratings-count">{ratings} ratings</p></div>
              <div class="beer-content">
                <h3>{name}</h3>
                <p class="brewery">{brewery}</p>
                <p class="meta">{metadata}</p>
                {production_status}
              </div>
            </article>
            """.format(
                rating=beer.rating,
                image=image,
                image_class=" has-label" if image else "",
                production_status=production_status,
                name=linked_name,
                brewery=escape(beer.brewery),
                metadata=metadata,
                ratings=escape(beer.ratings),
                style_attr=_style_data_attribute(beer.type_name),
            )
            )
            continue

        query = escape(row.query)
        reason = escape(row.reason)
        candidate_cards: List[str] = []

        for candidate in row.candidates:
            image = _label_image(candidate.image_url, candidate.image_hd_url, candidate.name)
            production_status = _production_html(candidate.production)
            for note in candidate.notes:
                production_status += '<p class="manual-note">' + escape(note) + '</p>'
            if candidate.abv_mismatch:
                production_status += '<p class="manual-note"><strong>ABV differs from the menu — verify before confirming.</strong></p>'
            candidate_cards.append(
                """
                <li class="candidate-card{image_class}"{style_attr}>
                  {image}
                  <div class="rating-column"><div class="rating-badge">{rating}</div>
                    <p class="ratings-count">{ratings} ratings</p></div>
                  <div>
                    <div class="candidate-heading"><h4>{name}</h4>
                      <span class="candidate-score">{score}</span></div>
                    <p class="brewery">{brewery}</p>
                    <p class="meta">{metadata}</p>
                    {production_status}
                  </div>
                </li>
                """.format(
                    score=candidate.score,
                    image=image,
                    image_class=" has-label" if image else "",
                    production_status=production_status,
                    name=_linked_name(candidate.name, candidate.url),
                    brewery=escape(candidate.brewery),
                    metadata=_meta_parts(
                        [
                            candidate.abv,
                            candidate.type_name,
                        ]
                    ),
                    rating=candidate.rating,
                    ratings=escape(candidate.ratings),
                    style_attr=_style_data_attribute(candidate.type_name),
                )
            )

        if row.best_guess is not None:
            candidate_cards.append(
                """
                <li class="candidate-card">
                  <div class="candidate-score">Best guess</div>
                  <div><h4>{name}</h4></div>
                </li>
                """.format(name=_linked_name(row.best_guess.name, row.best_guess.url))
            )

        excluded_links = []
        for excluded in row.excluded:
            excluded_links.append('<li class="excluded-candidate"><h4>' +
                _linked_name(excluded.link.name, excluded.link.url) + '</h4><p class="meta">' +
                _meta_parts([excluded.brewery, excluded.abv]) +
                '</p><p class="review-reason">' + escape(excluded.reason) + '</p></li>')
        excluded_html = ('<div class="excluded-candidates"><p class="review-reason">Excluded from matching — links for inspection only.</p>'
                         '<ul>' + "".join(excluded_links) + '</ul></div>') if excluded_links else ""
        candidates_html = "".join(candidate_cards) or ("" if excluded_links else '<p class="empty">No linked candidate was available.</p>')
        menu_abv_text = escape(row.menu_abv)
        search_warning = (
            '<p class="review-reason">' + escape(row.search_warning) + '</p>'
            if row.search_warning else ""
        )
        result_cards.append(
            """
            <article class="review-group" data-item-id="{item_id}" data-status="{status_key}" data-initial-selection="{initial_selection}" data-automatic-selection="{automatic_selection}">
              <div class="review-heading">
                <span class="status-pill">{status}</span>
                <h3>{query}</h3>
              </div>
              <p class="meta menu-abv">Menu ABV: {menu_abv}</p>
              <p class="review-reason">{reason}</p>
              {search_warning}
              <ol class="candidate-list">{candidates}</ol>{excluded}
            </article>
            """.format(automatic_selection=escape(row.automatic_selection, quote=True), menu_abv=menu_abv_text, item_id=row.item_id, status=escape(row.status), status_key=escape(row.status_key, quote=True), initial_selection=escape(row.initial_selection, quote=True), query=query, reason=reason, search_warning=search_warning, candidates=candidates_html, excluded=excluded_html)
        )

    return "".join(result_cards) or '<p class="empty">No beers.</p>'


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
    ambiguous_count = sum(result.get("status") == "ambiguous" for result in results)
    failed_count = sum(result.get("status") == "failed" for result in results)
    other_count = len(needs_review) - ambiguous_count - failed_count
    status_summary = f"{len(results)} beers · {len(confirmed)} confirmed · {ambiguous_count} ambiguous"
    if failed_count:
        status_summary += f" · {failed_count} failed"
    if other_count:
        status_summary += f" · {other_count} unresolved"
    not_attempted = sum(r.get("status") == "not_attempted" for r in results)
    rate_limited = sum(r.get("status") == "rate_limited" for r in results)
    # Older snapshots may have only the rate-limited row plus this count.
    omitted = sum(int(r.get("batch_remaining") or 0) for r in results
                  if r.get("status") == "rate_limited") if not not_attempted else 0
    incomplete_warning = ""
    if not_attempted or rate_limited or omitted:
        incomplete_warning = (
            '<p class="review-reason" role="alert"><strong>Incomplete run:</strong> '
            f'{not_attempted + omitted} menu rows were not searched; {rate_limited} rows were rate-limited. '
            'When searching is available, use <code>untap run --continue &lt;run-folder&gt;</code>. This report cannot be published.</p>'
        )
    style_groups = _style_groups(results)

    results_html = _render_result_cards(results)

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

    status_filters_html = (
        '<fieldset class="style-filters status-filters"><legend>Show</legend>'
        '<div class="style-chips">'
        '<label class="style-chip"><input type="radio" name="status-filter" '
        'data-status-filter value="all" checked><span>All results</span></label>'
        '<label class="style-chip"><input type="radio" name="status-filter" '
        'data-status-filter value="ambiguous"><span>Ambiguous</span></label>'
        '<label class="style-chip"><input type="radio" name="status-filter" '
        'data-status-filter value="failed"><span>Failed</span></label>'
        '</div></fieldset>'
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
  <meta name="untap-ambiguous-count" content="{ambiguous_count}">
  <meta name="untap-failed-count" content="{failed_count}">
  <meta name="untap-not-attempted-count" content="{not_attempted_count}">
  <meta name="untap-rate-limited-count" content="{rate_limited_count}">
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
    .status-filters {{ margin-bottom: 0; }}
    .status-filters + .style-filters {{ margin-top: 12px; }}
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
    .beer-card, .candidate-card, .review-group {{ border: 1px solid color-mix(in srgb, CanvasText 12%, transparent); border-radius: 14px; background: color-mix(in srgb, Canvas 94%, CanvasText 6%); }}
    .beer-card {{ display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 14px; padding: 12px 14px; align-items: start; }}
    .beer-card.has-label {{ grid-template-columns: 72px 64px minmax(0, 1fr); }}
    .beer-label {{ width: 72px; height: 72px; object-fit: contain; border-radius: 10px; background: color-mix(in srgb, Canvas 88%, CanvasText 12%); }}
    .label-preview-button {{ display: block; padding: 0; border: 0; border-radius: 10px; background: transparent; cursor: zoom-in; }}
    .label-preview-button:hover {{ outline: 2px solid LinkText; outline-offset: 2px; }}
    .label-preview-button:focus-visible {{ outline: 3px solid LinkText; outline-offset: 3px; }}
    .rating-badge {{ font-size: 1.35rem; font-weight: 750; font-variant-numeric: tabular-nums; }}
    .beer-content h3, .candidate-card h4 {{ margin-bottom: 5px; }}
    .beer-link {{ color: LinkText; text-decoration-thickness: 1px; text-decoration-color: color-mix(in srgb, LinkText 55%, transparent); text-underline-offset: .18em; overflow-wrap: anywhere; }}
    .beer-link:hover {{ text-decoration-color: LinkText; text-decoration-thickness: 2px; }}
    .beer-link:focus-visible {{ outline: 2px solid LinkText; outline-offset: 3px; border-radius: 2px; }}
    .brewery {{ margin-bottom: 4px; line-height: 1.4; opacity: .85; }}
    .meta {{ font-size: .9rem; }}
    .rating-column .ratings-count {{ font-size: .75rem; margin: 5px 0 0; }}
    .meta, .ratings-count, .review-reason {{ margin-bottom: 4px; opacity: .75; line-height: 1.4; }}
    .review-group > .menu-abv, .review-group > .review-reason {{ font-size: .9rem; margin: 0 0 4px; }}
    .production-status {{ min-height: 1.35em; margin: 6px 0 0; opacity: .72; font-size: .8rem; line-height: 1.35; }}
    .review-group {{ padding: 16px; }}
    .review-heading {{ display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }}
    .review-heading h3 {{ margin-bottom: 8px; }}
    .status-pill {{ border: 1px solid currentColor; border-radius: 999px; padding: 2px 8px; font-size: .78rem; font-weight: 700; opacity: .78; }}
    .candidate-list {{ margin-top: 12px; }}
    .candidate-card {{ display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 12px; padding: 12px; align-items: start; }}
    .candidate-card.has-label {{ grid-template-columns: 72px 64px minmax(0, 1fr); }}
    .candidate-heading {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; margin-bottom: 5px; }}
    .candidate-heading h4 {{ margin-bottom: 0; }}
    .label-dialog {{ width: min(92vw, 820px); max-height: 92vh; padding: 44px 18px 18px; border: 1px solid color-mix(in srgb, CanvasText 24%, transparent); border-radius: 16px; background: Canvas; color: CanvasText; }}
    .label-dialog::backdrop {{ background: rgb(0 0 0 / 78%); }}
    .label-dialog img {{ display: block; width: 100%; max-height: calc(92vh - 62px); object-fit: contain; }}
    .label-dialog-close {{ position: absolute; top: 10px; right: 10px; min-width: 34px; min-height: 34px; border: 1px solid color-mix(in srgb, CanvasText 30%, transparent); border-radius: 999px; background: Canvas; color: CanvasText; cursor: pointer; font-size: 1.2rem; }}
    .candidate-score {{ font-size: .75rem; font-weight: 600; font-variant-numeric: tabular-nums; border: 1px solid color-mix(in srgb, CanvasText 20%, transparent); border-radius: 6px; padding: 2px 6px; white-space: nowrap; }}
    .empty {{ opacity: .65; font-style: italic; }}
    @media (prefers-reduced-motion: reduce) {{
      .style-chip span, .style-chip span::before {{ transition: none; }}
    }}
    @media (max-width: 520px) {{
      main {{ padding: 18px 12px 36px; }}
      .beer-card {{ grid-template-columns: 54px 1fr; }}
      .beer-card.has-label {{ grid-template-columns: 54px 1fr; }}
      .beer-card.has-label .label-preview-button, .beer-card.has-label > .beer-label {{ grid-row: span 2; }}
      .beer-card.has-label .beer-label {{ width: 54px; height: 54px; }}
      .candidate-card {{ grid-template-columns: 1fr; gap: 4px; }}
      .candidate-card.has-label {{ grid-template-columns: 54px 1fr; }}
      .candidate-card.has-label .label-preview-button, .candidate-card.has-label > .beer-label {{ grid-row: span 2; }}
      .candidate-card.has-label .beer-label {{ width: 54px; height: 54px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{heading}</h1>
      <p class="summary">{status_summary}</p>
      {incomplete_warning}
    </header>

    {status_filters}
    {style_filters}

    <section aria-labelledby="results-heading">
      <h2 id="results-heading">Results</h2>
      <div class="results-list">{results_html}</div>
    </section>
  </main>
  <dialog class="label-dialog" id="label-dialog" aria-label="Beer label preview">
    <button class="label-dialog-close" type="button" aria-label="Close label preview">×</button>
    <img alt="" referrerpolicy="no-referrer">
  </dialog>
  <script>
    (function () {{
      const filters = Array.from(document.querySelectorAll('input[data-style-filter]'));
      const statusFilters = Array.from(document.querySelectorAll('input[data-status-filter]'));

      const beerCards = Array.from(document.querySelectorAll('.beer-card'));
      const candidateCards = Array.from(document.querySelectorAll('.candidate-card'));
      const reviewGroups = Array.from(document.querySelectorAll('.review-group'));

      function applyStyleFilters() {{
        const enabled = new Set(
          filters.filter((filter) => filter.checked).map((filter) => filter.value)
        );

        const selectedStatus = statusFilters.find((filter) => filter.checked).value;
        const statusVisible = (card) => selectedStatus === 'all' || card.dataset.status === selectedStatus;

        beerCards.forEach((card) => {{
          const styleVisible = !card.dataset.styleGroup || enabled.has(card.dataset.styleGroup);
          card.hidden = !styleVisible || !statusVisible(card);
        }});

        candidateCards.forEach((card) => {{
          card.hidden = Boolean(card.dataset.styleGroup) && !enabled.has(card.dataset.styleGroup);
        }});

        reviewGroups.forEach((group) => {{
          const candidates = Array.from(group.querySelectorAll('.candidate-card'));
          group.hidden = !statusVisible(group) ||
            (candidates.length && candidates.every((candidate) => candidate.hidden));
        }});
      }}

      filters.forEach((filter) => filter.addEventListener('change', applyStyleFilters));
      statusFilters.forEach((filter) => filter.addEventListener('change', applyStyleFilters));
      applyStyleFilters();

      const dialog = document.getElementById('label-dialog');
      const dialogImage = dialog.querySelector('img');
      const closeButton = dialog.querySelector('.label-dialog-close');
      let opener = null;

      document.querySelectorAll('[data-label-preview]').forEach((button) => {{
        button.addEventListener('click', () => {{
          opener = button;
          dialogImage.src = button.dataset.labelPreview;
          dialogImage.alt = button.querySelector('img').alt;
          if (typeof dialog.showModal === 'function') dialog.showModal();
          else window.open(button.dataset.labelPreview, '_blank', 'noopener,noreferrer');
        }});
      }});

      closeButton.addEventListener('click', () => dialog.close());
      dialog.addEventListener('click', (event) => {{
        if (event.target === dialog) dialog.close();
      }});
      dialog.addEventListener('close', () => {{
        dialogImage.removeAttribute('src');
        if (opener) opener.focus();
      }});
    }})();
  </script>
  <meta name="untap-selection-report-id" content="{selection_id}">
  <script id="manual-review-script">{review_script}</script>
</body>
</html>
""".format(
        title=escape(clean_title),
        meta_title=escape(clean_title, quote=True),
        heading=escape(clean_title),
        report_date=escape(generated_date, quote=True),
        total=len(results),
        confirmed_count=len(confirmed),
        not_attempted_count=not_attempted + omitted,
        rate_limited_count=rate_limited,
        incomplete_warning=incomplete_warning,
        review_count=len(needs_review),
        ambiguous_count=ambiguous_count,
        failed_count=failed_count,
        status_summary=status_summary,
        style_filters=style_filters_html,
        status_filters=status_filters_html,
        results_html=results_html,
        selection_id=selection_report_id(results, clean_title, generated_date),
        review_script=files("untap.assets").joinpath("untap_review.js").read_text(encoding="utf-8"),
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
