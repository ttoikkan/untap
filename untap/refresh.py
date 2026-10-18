"""Rebuild a saved run offline, optionally publishing to a local archive."""

import argparse
import json
from datetime import datetime, timezone
from copy import deepcopy
import sys
from uuid import uuid4
from pathlib import Path
from typing import Optional, Sequence

from untap.run_output import write_run_outputs
from untap.publish import PublishError, publish_report, record_archive_refresh_status
from untap.report import render_html_report
from untap.review_policy import selection_report_id, sorted_review_results, review_candidates, available_review_candidate
from untap.snapshot import load_snapshot
from untap.refresh_config import config_defaults
from untap.manual_candidates import parse_beer_url, fetch_candidates


def apply_selections(snapshot, path: Path, fetch_pending: bool = False) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    apply_selection_payload(snapshot, payload, fetch_pending)


def apply_selection_payload(snapshot, payload, fetch_pending: bool = False) -> None:
    results = [item["result"] for item in snapshot["items"]]
    expected = selection_report_id(results, snapshot["report"]["title"], snapshot["report"]["date"])
    if (not isinstance(payload, dict) or payload.get("format") != "untap-manual-review-trial-v1"
            or payload.get("report_id") != expected or not isinstance(payload.get("selections"), list)):
        raise ValueError("Selections do not match this snapshot. Refresh the report with the current version, then export selections again.")
    ordered = sorted_review_results(results)
    pending = payload.get("pending_candidates", [])
    if not isinstance(pending, list) or len(pending) > 20:
        raise ValueError("At most 20 pending candidates are allowed")
    additions = []
    pending_seen = set()
    for entry in pending:
        if not isinstance(entry, dict):
            raise ValueError("Invalid pending candidate")
        item = next((i for i in snapshot["items"] if i["id"] == entry.get("item_id")), None)
        if item is None or (item["result"].get("status") not in ("failed", "ambiguous")
                            and not item["result"].get("manually_confirmed")):
            raise ValueError("Pending candidate has an invalid menu item")
        beer_id, url, _ = parse_beer_url(entry.get("url"))
        pending_key = (item["id"], beer_id)
        if pending_key in pending_seen:
            raise ValueError("Duplicate pending candidate")
        pending_seen.add(pending_key)
        existing_ids = set()
        for existing_candidate in review_candidates(item["result"]):
            try:
                existing_ids.add(parse_beer_url(existing_candidate.get("url"))[0])
            except ValueError:
                pass
        if beer_id in existing_ids:
            raise ValueError("Pending beer is already an available candidate")
        additions.append((item, beer_id, url))
    if additions and not fetch_pending:
        raise ValueError("Pending URLs require explicit --fetch-candidates (uses Untappd)")
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
        candidate = available_review_candidate(result, url)
        if candidate is None:
            raise ValueError("Selection is not an available review candidate")
        item = next(item for item in snapshot["items"] if item["result"] is result)
        validated.append((item, candidate, url))
    # No network until every row and URL in the export has passed validation.
    fetched = fetch_candidates([url for _, _, url in additions]) if additions else {}
    for item, beer_id, url in additions:
        target = item["result"]
        snapshot.setdefault("candidate_additions", []).append({
            "item_id": item["id"], "url": url, "original_result": deepcopy(target)})
        field = "same_abv_variants" if target.get("same_abv_variants") else "alternatives"
        target.setdefault(field, []).append(deepcopy(fetched[beer_id]))
        if target.get("status") == "failed":
            target["status"] = "ambiguous"
            target["reason"] = "User-added candidate awaiting manual confirmation"
    for item, candidate, url in validated:
        original = deepcopy(item["result"])
        result = item["result"]
        for key in ("brewery", "rating", "ratings", "abv", "type_name", "image_url", "image_hd_url", "in_production", "score"):
            result[key] = candidate.get(key)
        # Candidate records do not carry detail-page IBU or search snippets.
        # Never inherit those values from the previously selected beer.
        result["ibu"] = None
        result.pop("search_text", None)
        result.pop("search_fallback", None)
        result.pop("match", None)
        abv = candidate.get("abv")
        result["abv"] = None if abv is None else f"{float(abv):g}%"
        result["status"] = "ok"
        result["beer"] = str(candidate.get("name") or "")
        result["url"] = url
        result["manually_confirmed"] = True
        result.pop("reason", None)
        result.pop("search_warning", None)
        snapshot["manual_decisions"].append({"item_id": item["id"], "url": url, "original_result": original})


def refresh(source: Path, output: Optional[Path] = None, selections: Optional[Path] = None,
            fetch_pending: bool = False, csv_requested: bool = False) -> Path:
    """Keep the snapshot's data, IDs, title and date; create fresh presentation."""
    source = source / "results.json" if source.is_dir() else source
    snapshot = load_snapshot(source)
    if selections is not None:
        apply_selections(snapshot, selections, fetch_pending)
    return write_reviewed_run(snapshot, source, output, csv_requested=csv_requested)


def write_reviewed_run(snapshot, source: Path, output: Optional[Path] = None, csv_requested: bool = False) -> Path:
    """Write self-contained reviewed outputs without changing their source."""
    snapshot = deepcopy(snapshot)
    snapshot["report"]["rebuilt_at"] = datetime.now(timezone.utc).isoformat()
    results = [item["result"] for item in snapshot["items"]]
    # Render before creating output so invalid results cannot leave a report.
    html = render_html_report(results, snapshot["report"]["title"], snapshot["report"]["date"],
                              source_created_at=snapshot.get("created_at"),
                              rebuilt_at=snapshot["report"].get("rebuilt_at"))
    if output is None:
        output = source.parent.parent / (source.parent.name + "_refresh_" + uuid4().hex)
        output.mkdir()
    else:
        output.mkdir(exist_ok=False)
    write_run_outputs(snapshot, output, csv_requested=csv_requested, html=html)
    return output


def refresh_batch(config_path: Path, csv_requested: bool = False) -> int:
    """Validate configuration first, then run independent entries sequentially."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    defaults = config_defaults(config)
    if not config["reports"]:
        raise ValueError("Batch configuration requires a nonempty reports list")
    jobs = []
    for entry in config["reports"]:
        if not isinstance(entry, dict) or set(entry) - {"source", "archive", "selections", "replace"}:
            raise ValueError("Invalid batch entry or unknown field")
        entry = {**defaults, **entry}
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
        if csv_requested:
            arguments.append("--csv")
        jobs.append((entry["source"], arguments))
    failures = 0
    for source, arguments in jobs:
        print(f"\nRefreshing: {source}")
        status = main(arguments)
        failures += status != 0
        print(f"{'FAILED' if status else 'OK'}: {source}")
    print(f"\nBatch complete: {len(jobs) - failures} succeeded, {failures} failed")
    return 2 if failures else 0



def _record_outcome(source: Path, archive: Optional[Path], title: Optional[str], outcome: str) -> None:
    """Status writes are diagnostic; never turn a refresh error into a success."""
    if not source.exists():
        return
    attempted_at = datetime.now(timezone.utc).isoformat()
    directory = source if source.is_dir() else source.parent
    try:
        status = {"outcome": outcome, "attempted_at": attempted_at,
                  "operation": "rebuild_and_publish" if archive else "rebuild"}
        # Atomic replacement preserves a prior status if writing fails.
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".refresh-status-", delete=False) as handle:
            temporary = Path(handle.name)
            try:
                json.dump(status, handle, indent=2)
                handle.write("\n")
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, directory / "refresh-status.json")
        finally:
            temporary.unlink(missing_ok=True)
    except (OSError, ValueError) as exc:
        print(f"Could not save refresh status: {exc}", file=sys.stderr)
    if archive is not None and title:
        try:
            record_archive_refresh_status(archive, title, outcome, attempted_at)
        except (OSError, ValueError, TypeError) as exc:
            print(f"Could not update archive refresh status: {exc}", file=sys.stderr)


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", nargs="?", type=Path, help="run directory or results.json")
    parser.add_argument("--batch", type=Path, help="JSON configuration listing saved runs to refresh")
    parser.add_argument("--output", type=Path, help="new output directory (must not exist)")
    parser.add_argument("--selections", type=Path, help="exported selections from this snapshot's report")
    parser.add_argument("--fetch-candidates", action="store_true", help="explicitly fetch pending Untappd URLs in the export")
    parser.add_argument("--archive", type=Path, help="optionally update this local archive")
    parser.add_argument("--csv", action="store_true", help="also export results.csv")
    parser.add_argument("--replace", action="store_true", help="allow replacing the same logical report in the archive")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    configure_parser(parser)
    return run_options(parser.parse_args(argv), parser)


def run_options(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.batch:
        if args.source or args.output or args.selections or args.archive or args.replace or args.fetch_candidates:
            parser.error("--batch cannot be combined with single-run arguments")
        try:
            return refresh_batch(args.batch, csv_requested=args.csv)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            print(f"Batch failed: {exc}", file=sys.stderr)
            return 2
    if args.source is None:
        parser.error("provide a source or --batch")
    if args.fetch_candidates and not args.selections:
        parser.error("--fetch-candidates requires --selections")
    if args.replace and args.archive is None:
        parser.error("--replace requires --archive")
    title = None
    try:
        original = args.source / "results.json" if args.source.is_dir() else args.source
        title = load_snapshot(original)["report"]["title"]
        output = refresh(args.source, args.output, args.selections, args.fetch_candidates, args.csv)
        print(f"Refreshed run: {output.resolve()}")
        if args.archive is not None:
            published = publish_report(output / "results.html", args.archive, replace=args.replace)
            print(f"Published locally: {args.archive / 'reports' / published.filename}")
    except (OSError, ValueError, TypeError, KeyError, PublishError) as exc:
        _record_outcome(args.source, args.archive, title, "failed")
        print(f"Refresh failed: {exc}", file=sys.stderr)
        return 2
    _record_outcome(args.source, args.archive, title, "succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
