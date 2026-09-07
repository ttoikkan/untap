"""Rebuild a saved run offline, optionally publishing to a local archive."""

import argparse
import json
from copy import deepcopy
import sys
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from untap_batch import save_csv
from untap_publish import PublishError, publish_report
from untap_report import render_html_report, selection_report_id, _sorted_report_results, _review_candidates
from untap_snapshot import load_snapshot, save_snapshot


def apply_selections(snapshot, path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    results = [item["result"] for item in snapshot["items"]]
    expected = selection_report_id(results, snapshot["report"]["title"], snapshot["report"]["date"])
    if (not isinstance(payload, dict) or payload.get("format") != "untap-manual-review-trial-v1"
            or payload.get("report_id") != expected or not isinstance(payload.get("selections"), list)):
        raise ValueError("Selections do not match this snapshot. Refresh the report with the current version, then export selections again.")
    ordered = _sorted_report_results(results)
    seen = set()
    validated = []
    for entry in payload["selections"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid selection")
        row, url = entry.get("row"), entry.get("url")
        if type(row) is not int or row < 0 or row >= len(ordered) or row in seen:
            raise ValueError("Invalid or duplicate selection row")
        seen.add(row)
        result = ordered[row]
        candidate = next((c for c in _review_candidates(result) if c.get("url") == url), None)
        if (result.get("status") != "ambiguous" and not result.get("manually_confirmed")) or not isinstance(url, str) or not url.startswith("https://untappd.com/b/") or candidate is None:
            raise ValueError("Selection is not an available ambiguous candidate")
        item = next(item for item in snapshot["items"] if item["result"] is result)
        validated.append((item, candidate, url))
    for item, candidate, url in validated:
        original = deepcopy(item["result"])
        result = item["result"]
        for key in ("brewery", "rating", "ratings", "abv", "type_name", "image_url", "image_hd_url", "in_production", "score"):
            result[key] = candidate.get(key)
        result["status"] = "ok"
        result["beer"] = str(candidate.get("name") or "")
        result["url"] = url
        result["manually_confirmed"] = True
        result.pop("reason", None)
        result.pop("search_warning", None)
        snapshot["manual_decisions"].append({"item_id": item["id"], "url": url, "original_result": original})


def refresh(source: Path, output: Optional[Path] = None, selections: Optional[Path] = None) -> Path:
    """Keep the snapshot's data, IDs, title and date; create fresh presentation."""
    source = source / "results.json" if source.is_dir() else source
    snapshot = load_snapshot(source)
    if selections is not None:
        apply_selections(snapshot, selections)
    results = [item["result"] for item in snapshot["items"]]
    # Render before creating output so invalid results cannot leave a report.
    html = render_html_report(results, snapshot["report"]["title"], snapshot["report"]["date"])
    if output is None:
        output = Path(tempfile.mkdtemp(prefix=source.parent.name + "_refresh_", dir=source.parent.parent))
    else:
        output.mkdir(exist_ok=False)
    save_snapshot(snapshot, output / "results.json")
    (output / "results.html").write_text(html, encoding="utf-8")
    save_csv(results, str(output / "results.csv"))
    return output


def refresh_batch(config_path: Path) -> int:
    """Validate configuration first, then run independent entries sequentially."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) != {"reports"} or not isinstance(config["reports"], list) or not config["reports"]:
        raise ValueError("Batch configuration requires a nonempty reports list")
    jobs = []
    for entry in config["reports"]:
        if not isinstance(entry, dict) or set(entry) - {"source", "archive", "selections", "replace"}:
            raise ValueError("Invalid batch entry or unknown field")
        if not isinstance(entry.get("source"), str) or not entry["source"].strip():
            raise ValueError("Each batch entry requires a source path")
        if type(entry.get("replace", False)) is not bool:
            raise ValueError("replace must be true or false")
        if entry.get("replace") and not entry.get("archive"):
            raise ValueError("replace requires an archive")
        arguments = []
        for field in ("source", "archive", "selections"):
            if field not in entry:
                continue
            if not isinstance(entry[field], str) or not entry[field].strip():
                raise ValueError(f"{field} must be a nonempty path")
            path = Path(entry[field]).expanduser()
            if not path.is_absolute():
                path = config_path.resolve().parent / path
            if field != "source":
                arguments.append("--" + field)
            arguments.append(str(path))
        if entry.get("replace", False):
            arguments.append("--replace")
        jobs.append((entry["source"], arguments))
    failures = 0
    for source, arguments in jobs:
        print(f"\nRefreshing: {source}")
        status = main(arguments)
        failures += status != 0
        print(f"{'FAILED' if status else 'OK'}: {source}")
    print(f"\nBatch complete: {len(jobs) - failures} succeeded, {failures} failed")
    return 2 if failures else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, help="run directory or results.json")
    parser.add_argument("--batch", type=Path, help="JSON configuration listing saved runs to refresh")
    parser.add_argument("--output", type=Path, help="new output directory (must not exist)")
    parser.add_argument("--selections", type=Path, help="exported selections from this snapshot's report")
    parser.add_argument("--archive", type=Path, help="optionally update this local archive")
    parser.add_argument("--replace", action="store_true", help="allow replacing the same logical report in the archive")
    args = parser.parse_args(argv)
    if args.batch:
        if args.source or args.output or args.selections or args.archive or args.replace:
            parser.error("--batch cannot be combined with single-run arguments")
        try:
            return refresh_batch(args.batch)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            print(f"Batch failed: {exc}", file=sys.stderr)
            return 2
    if args.source is None:
        parser.error("provide a source or --batch")
    if args.replace and args.archive is None:
        parser.error("--replace requires --archive")
    try:
        output = refresh(args.source, args.output, args.selections)
        print(f"Refreshed run: {output.resolve()}")
        if args.archive is not None:
            published = publish_report(output / "results.html", args.archive, replace=args.replace)
            print(f"Published locally: {args.archive / 'reports' / published.filename}")
    except (OSError, ValueError, TypeError, KeyError, PublishError) as exc:
        print(f"Refresh failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
