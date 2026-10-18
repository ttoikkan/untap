"""Offline serialization of saved runs; callers own directories and recovery."""
import csv
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, cast

from untap.types import MatchResult
from untap.snapshot import save_snapshot
from untap.report import render_html_report


CSV_FIELDS = (
    "original_menu_text",
    "input_brewery",
    "input_beer",
    "input_abv",
    "input_style",
    "query",
    "status",
    "beer",
    "brewery",
    "rating",
    "ratings",
    "abv",
    "ibu",
    "type_name",
    "score",
    "reason",
    "alternatives",
    "url",
)

def _format_candidate_list(items):
    """
    Render a list of candidate dicts (as produced for "alternatives" /
    "same_abv_variants") into a single readable CSV cell, e.g.:
      "Fresh (0.612, 6.5%); Fresh - Hazy (0.598, 6.5%)"
    """
    if not items:
        return ""

    parts = []

    for item in items[:5]:
        name = item.get("name") or ""
        score = item.get("score")
        abv = item.get("abv")

        score_str = f"{score:.3f}" if score is not None else "N/A"
        abv_str = f"{abv:g}%" if abv is not None else "N/A"

        parts.append(f"{name} ({score_str}, {abv_str})")

    return "; ".join(parts)








_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: Any) -> Any:
    """Prefix spreadsheet-formula triggers so Excel/Sheets show text, not a formula."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def save_csv(results: Sequence[MatchResult], filename: str) -> None:
    fields = CSV_FIELDS

    with open(
        filename,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        for r in results:
            # CSV_FIELDS is dynamic at runtime, so view the TypedDict through a
            # generic mapping for schema-driven serialization.
            r_mapping = cast(Mapping[str, Any], r)
            row = {
                field: r_mapping.get(
                    field,
                    "",
                )
                for field in fields
            }

            # "ok" results already have a confirmed "beer" field. Everything
            # else (ambiguous / low_confidence / failed) only ever stored the
            # best guess under "match" -- surface it in "beer" instead of
            # leaving the row blank.
            if not row["beer"] and r.get("match"):
                row["beer"] = r["match"]

            # Prefer same-ABV-family variants when present (they are the
            # more specific ambiguity explanation); fall back to the
            # general "alternatives" list otherwise.
            row["alternatives"] = _format_candidate_list(
                r.get("same_abv_variants") or r.get("alternatives") or []
            )

            writer.writerow({key: _csv_safe(value) for key, value in row.items()})

    print()
    print(
        f"Saved CSV: {filename}"
    )

def write_run_outputs(snapshot: Dict[str, Any], output: Path, *,
                      csv_requested: bool = False, html: Optional[str] = None,
                      csv_first: bool = False, use_snapshot_date: bool = True) -> None:
    """Write into an already reserved folder; propagate failures to the caller.

    Reviewed runs may supply HTML rendered before reserving their folder.
    Batch runs preserve CSV-before-HTML ordering and the renderer's current date.
    No metadata, IDs, journal files or source directories are changed here.
    """
    results = [item["result"] for item in snapshot["items"]]
    save_snapshot(snapshot, output / "results.json")
    if csv_requested and csv_first:
        save_csv(results, str(output / "results.csv"))
    if html is None:
        html = render_html_report(results, snapshot["report"]["title"],
                                  snapshot["report"]["date"] if use_snapshot_date else None,
                                  source_created_at=snapshot.get("created_at"),
                                  rebuilt_at=snapshot["report"].get("rebuilt_at"))
    with (output / "results.html").open("w", encoding="utf-8", newline="") as handle:
        handle.write(html)
    if csv_requested and not csv_first:
        save_csv(results, str(output / "results.csv"))
