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
import shutil
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
    body {{
      max-width: 800px;
      margin: 0 auto;
      padding: 2rem 1rem;
      font-family: system-ui, -apple-system, sans-serif;
      line-height: 1.5;
    }}
    h1 {{ margin-bottom: 0.25rem; }}
    .subtitle {{ color: #666; margin-bottom: 2rem; }}
    .report-card {{ padding: 1rem 0; border-top: 1px solid #ddd; }}
    .report-card a {{ font-size: 1.15rem; font-weight: 600; }}
    .meta {{ color: #666; margin-top: 0.25rem; }}
  </style>
</head>
<body>
  <h1>Untap Results</h1>
  <p class="subtitle">Archive of beer rating reports generated by Untap.</p>

  <h2>Reports</h2>
{report_markup}
</body>
</html>
"""


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


def publish_report(source_report: Path, archive_root: Path) -> ArchiveReport:
    """Publish one report into a local archive and regenerate its index."""
    metadata = read_report_metadata(source_report)
    if not archive_root.is_dir():
        raise PublishError(f"archive directory does not exist: {archive_root}")

    reports_dir = archive_root / "reports"
    if not reports_dir.is_dir():
        raise PublishError(f"archive reports directory does not exist: {reports_dir}")

    filename = archive_filename(metadata)
    destination = reports_dir / filename
    if destination.exists():
        raise PublishError(f"refusing to overwrite existing report: {destination}")

    existing_reports = _archive_reports(reports_dir)
    new_report = ArchiveReport(metadata=metadata, filename=filename)
    index_html = render_archive_index([*existing_reports, new_report])

    shutil.copyfile(source_report, destination)
    try:
        _atomic_write_text(archive_root / "index.html", index_html)
    except BaseException:
        try:
            destination.unlink()
        except FileNotFoundError:
            pass
        raise
    return new_report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish an Untap HTML report into a local static archive."
    )
    parser.add_argument("report", type=Path, help="completed Untap HTML report")
    parser.add_argument("archive", type=Path, help="local untap-results repository root")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        published = publish_report(args.report, args.archive)
    except (OSError, PublishError) as exc:
        print(f"Publish failed: {exc}", file=sys.stderr)
        return 2

    metadata = published.metadata
    print("Published locally:")
    print(f"  {metadata.title}")
    print(f"  reports/{published.filename}")
    print("\nArchive index updated.")
    print("\nNext:")
    print("  git add .")
    print(f"  git commit -m {shlex.quote('Publish ' + metadata.title)}")
    print("  git push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
