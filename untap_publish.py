"""Local archive publisher for completed Untap HTML reports.

This utility is intentionally separate from the Untap runtime. It validates the
machine-readable metadata embedded by ``untap_report.py``, copies a report into
a local static-site archive, and regenerates the archive index. It performs no
Git operations, GitHub API calls, browser automation, or network requests.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import os
import re
import shlex
import sys
import tempfile
import unicodedata
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


REQUIRED_META_NAMES = (
    "untap-report-title",
    "untap-report-date",
    "untap-total-beers",
    "untap-confirmed-count",
    "untap-review-count",
)


class PublishError(ValueError):
    """Raised when a report or archive cannot be published safely."""


@dataclass(frozen=True)
class ReportMetadata:
    title: str
    report_date: str
    total_beers: int
    confirmed_count: int
    review_count: int


@dataclass(frozen=True)
class ArchiveReport:
    metadata: ReportMetadata
    filename: str


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: Dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.casefold() != "meta":
            return
        attr_map = {key.casefold(): value for key, value in attrs}
        name = (attr_map.get("name") or "").strip()
        if name not in REQUIRED_META_NAMES:
            return
        content = attr_map.get("content")
        if content is None:
            return
        if name in self.values:
            raise PublishError(f"duplicate report metadata field: {name}")
        self.values[name] = content.strip()


def _parse_nonnegative_int(name: str, value: str) -> int:
    if not re.fullmatch(r"\d+", value):
        raise PublishError(f"invalid {name}: expected a non-negative integer")
    return int(value)


def read_report_metadata(path: Path) -> ReportMetadata:
    """Validate and return the v78+ metadata contract from one HTML report."""
    if not path.is_file():
        raise PublishError(f"report does not exist: {path}")
    if path.suffix.casefold() != ".html":
        raise PublishError("report must be an .html file")

    parser = _MetaParser()
    try:
        parser.feed(path.read_text(encoding="utf-8"))
        parser.close()
    except UnicodeDecodeError as exc:
        raise PublishError("report is not valid UTF-8 HTML") from exc

    missing = [name for name in REQUIRED_META_NAMES if not parser.values.get(name)]
    if missing:
        raise PublishError("missing Untap report metadata: " + ", ".join(missing))

    title = parser.values["untap-report-title"].strip()
    if not title:
        raise PublishError("report title must not be empty")

    report_date = parser.values["untap-report-date"]
    try:
        parsed_date = date.fromisoformat(report_date)
    except ValueError as exc:
        raise PublishError("invalid untap-report-date: expected YYYY-MM-DD") from exc
    if parsed_date.isoformat() != report_date:
        raise PublishError("invalid untap-report-date: expected canonical YYYY-MM-DD")

    total = _parse_nonnegative_int("untap-total-beers", parser.values["untap-total-beers"])
    confirmed = _parse_nonnegative_int(
        "untap-confirmed-count", parser.values["untap-confirmed-count"]
    )
    review = _parse_nonnegative_int("untap-review-count", parser.values["untap-review-count"])
    if total != confirmed + review:
        raise PublishError(
            "inconsistent report counts: total must equal confirmed plus needs-review"
        )

    return ReportMetadata(
        title=title,
        report_date=report_date,
        total_beers=total,
        confirmed_count=confirmed,
        review_count=review,
    )


def slugify_title(title: str) -> str:
    """Return a conservative ASCII URL slug for a human-readable report title."""
    normalized = unicodedata.normalize("NFKD", title)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug or "report"


def archive_filename(metadata: ReportMetadata) -> str:
    return f"{metadata.report_date}-{slugify_title(metadata.title)}.html"


def _report_identity(title: str) -> str:
    """Return the stable logical archive identity for a report title."""
    return " ".join(title.split()).casefold()


def _archive_reports(reports_dir: Path) -> List[ArchiveReport]:
    reports: List[ArchiveReport] = []
    for path in sorted(reports_dir.glob("*.html")):
        metadata = read_report_metadata(path)
        reports.append(ArchiveReport(metadata=metadata, filename=path.name))
    return reports


def _plural(value: int, singular: str, plural: Optional[str] = None) -> str:
    word = singular if value == 1 else (plural or singular + "s")
    return f"{value} {word}"


def render_archive_index(reports: Iterable[ArchiveReport]) -> str:
    ordered = sorted(
        reports,
        key=lambda report: (
            report.metadata.report_date,
            report.metadata.title.casefold(),
            report.filename.casefold(),
        ),
        reverse=True,
    )

    cards: List[str] = []
    for report in ordered:
        metadata = report.metadata
        parsed_date = date.fromisoformat(metadata.report_date)
        display_date = f"{parsed_date.strftime('%B')} {parsed_date.day}, {parsed_date.year}"
        href = "reports/" + report.filename
        summary = " · ".join(
            (
                display_date,
                _plural(metadata.total_beers, "beer"),
                f"{metadata.confirmed_count} confirmed",
                f"{metadata.review_count} need review",
            )
        )
        cards.append(
            "    <article class=\"report-card\">\n"
            f"      <a href=\"{escape(href, quote=True)}\">{escape(metadata.title)}</a>\n"
            f"      <div class=\"meta\">{escape(summary)}</div>\n"
            "    </article>"
        )

    report_markup = "\n".join(cards) if cards else "    <p>No reports published yet.</p>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Untap Results</title>
  <style>
    :root {{ color-scheme: light dark; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: Canvas; color: CanvasText; }}
    main {{ width: min(900px, 100%); margin: 0 auto; padding: 24px 16px 48px; }}
    header {{ margin-bottom: 28px; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(1.8rem, 6vw, 2.5rem); }}
    h2 {{ margin: 0 0 14px; }}
    .subtitle {{ margin: 0; opacity: .72; }}
    .report-list {{ display: grid; gap: 10px; }}
    .report-card {{ padding: 16px; border: 1px solid color-mix(in srgb, CanvasText 16%, transparent); border-radius: 14px; background: color-mix(in srgb, Canvas 94%, CanvasText 6%); }}
    .report-card a {{ color: LinkText; font-size: 1.15rem; font-weight: 700; text-decoration-thickness: .08em; text-underline-offset: .15em; }}
    .meta {{ margin-top: 5px; opacity: .75; line-height: 1.4; }}
    @media (max-width: 520px) {{
      main {{ padding: 18px 12px 36px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Untap Results</h1>
      <p class="subtitle">Archive of beer rating reports generated by Untap.</p>
    </header>

    <h2>Reports</h2>
    <section class="report-list">
{report_markup}
    </section>
  </main>
</body>
</html>
"""


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def publish_report(
    source_report: Path, archive_root: Path, *, replace: bool = False
) -> ArchiveReport:
    """Publish one report into a local archive and regenerate its index.

    A report's logical archive identity is its normalized descriptive title; the
    embedded report date is generation metadata, not identity. Existing logical
    reports remain protected by default. ``replace=True`` replaces exactly one
    existing title match at its existing filename, preserving the public URL.
    """
    metadata = read_report_metadata(source_report)
    if not archive_root.is_dir():
        raise PublishError(f"archive directory does not exist: {archive_root}")

    reports_dir = archive_root / "reports"
    if not reports_dir.is_dir():
        raise PublishError(f"archive reports directory does not exist: {reports_dir}")

    existing_reports = _archive_reports(reports_dir)
    identity = _report_identity(metadata.title)
    identity_matches = [
        report for report in existing_reports
        if _report_identity(report.metadata.title) == identity
    ]
    if len(identity_matches) > 1:
        filenames = ", ".join(report.filename for report in identity_matches)
        raise PublishError(
            "archive contains multiple reports with the same logical title: " + filenames
        )

    replacing = bool(identity_matches)
    if replacing and not replace:
        existing = identity_matches[0]
        raise PublishError(
            "refusing to replace existing logical report without --replace: "
            f"{reports_dir / existing.filename}"
        )

    if replacing:
        existing = identity_matches[0]
        filename = existing.filename
        destination = reports_dir / filename
        index_reports = [
            report for report in existing_reports if report.filename != filename
        ]
    else:
        filename = archive_filename(metadata)
        destination = reports_dir / filename
        if destination.exists():
            raise PublishError(
                "refusing to overwrite archive filename belonging to another report: "
                f"{destination}"
            )
        index_reports = existing_reports

    new_report = ArchiveReport(metadata=metadata, filename=filename)
    index_html = render_archive_index([*index_reports, new_report])

    source_bytes = source_report.read_bytes()
    previous_bytes = destination.read_bytes() if replacing else None
    _atomic_write_bytes(destination, source_bytes)
    try:
        _atomic_write_text(archive_root / "index.html", index_html)
    except BaseException:
        if previous_bytes is None:
            try:
                destination.unlink()
            except FileNotFoundError:
                pass
        else:
            _atomic_write_bytes(destination, previous_bytes)
        raise
    return new_report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish an Untap HTML report into a local static archive."
    )
    parser.add_argument("report", type=Path, help="completed Untap HTML report")
    parser.add_argument("archive", type=Path, help="local untap-results repository root")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="explicitly replace an existing report with the same logical title",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        metadata = read_report_metadata(args.report)
        reports_dir = args.archive / "reports"
        existing_reports = _archive_reports(reports_dir) if reports_dir.is_dir() else []
        identity = _report_identity(metadata.title)
        replacing = args.replace and any(
            _report_identity(report.metadata.title) == identity
            for report in existing_reports
        )
        published = publish_report(args.report, args.archive, replace=args.replace)
    except (OSError, PublishError) as exc:
        print(f"Publish failed: {exc}", file=sys.stderr)
        return 2

    metadata = published.metadata
    action = "Replace" if replacing else "Publish"
    print("Replaced locally:" if replacing else "Published locally:")
    print(f"  {metadata.title}")
    print(f"  reports/{published.filename}")
    print("\nArchive index updated.")
    print("\nNext:")
    print("  git add .")
    print(f"  git commit -m {shlex.quote(action + ' ' + metadata.title)}")
    print("  git push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
