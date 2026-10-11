"""Continue incomplete snapshots or recover interrupted batch journals.

Only rate-limited and unattempted rows are searched. Completed matches,
review decisions and item IDs remain intact. Sources are never overwritten.
"""
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from untap_matcher import DEFAULT_MIN_SCORE, MATCH_RESULT_STATUSES
from untap_batch import run_batch, unattempted_result, save_csv, debug_transcript
from untap_parser import read_validated_menu, validate_normalized_menu
from untap_snapshot import load_snapshot, save_snapshot, build_snapshot, menu_item_ids
from untap_report import render_html_report
from untap_untappd import untappd_browser_page

UNFINISHED = {"rate_limited", "not_attempted"}


def _search_input(result):
    """Reconstruct structured input without guessing identity from search text."""
    if not isinstance(result.get("query"), str) or not result["query"].strip():
        raise ValueError("Saved row has no valid search query")
    if result.get("input_beer"):
        abv = result.get("input_abv")
        item = {"query": result["query"], "original": result.get("original_menu_text") or result["query"],
                "brewery": result.get("input_brewery") or None,
                "beer": result["input_beer"], "menu_abv": None if abv in (None, "") else float(abv),
                "style": result.get("input_style") or None}
        validate_normalized_menu([item])
        return item
    return result["query"]


def _validate_saved_rows(snapshot):
    results = [item["result"] for item in snapshot["items"]]
    if [item["id"] for item in snapshot["items"]] != menu_item_ids(results):
        raise ValueError("Snapshot item identities are inconsistent")
    for result in results:
        if result.get("status") not in MATCH_RESULT_STATUSES:
            raise ValueError("Saved row has an unsupported status")
        _search_input(result)
    json.dumps(snapshot, allow_nan=False)
    return snapshot


def load_continuation(source: Path, recovery_menu: Optional[Path] = None) -> Dict[str, Any]:
    """Prefer final snapshots; recover journals against an explicit input manifest."""
    source = source.expanduser().resolve()
    directory = source if source.is_dir() else source.parent
    final = directory / "results.json" if source.is_dir() else source
    if final.name == "results.json" and final.exists():
        try:
            snapshot = load_snapshot(final)
        except json.JSONDecodeError:
            if not (directory / "results.input.json").exists() and recovery_menu is None:
                raise ValueError("Final snapshot is truncated and no recovery manifest is available")
            print("Recovery warning: final snapshot is truncated; recovering from the journal")
        else:
            _validate_saved_rows(snapshot)
            if any(item["result"].get("batch_remaining") for item in snapshot["items"]):
                omitted = sum(int(item["result"].get("batch_remaining") or 0) for item in snapshot["items"])
                placeholders = sum(item["result"].get("status") == "not_attempted" for item in snapshot["items"])
                if omitted > placeholders:
                    raise ValueError("Legacy truncated snapshot lacks remaining menu identities; rerun the full menu")
            return snapshot
    manifest = directory / "results.input.json"
    if manifest.exists():
        snapshot = load_snapshot(manifest)
    elif recovery_menu is not None:
        _, inputs = read_validated_menu(str(recovery_menu))
        snapshot = build_snapshot([unattempted_result(item, "Recovered unfinished row") for item in inputs], recovery_menu.stem)
    else:
        raise ValueError("No input manifest or final snapshot. For a v103 journal, supply --recovery-menu with the original TSV")
    _validate_saved_rows(snapshot)
    journal = directory / "results.partial.jsonl"
    raw = journal.read_text(encoding="utf-8")
    entries = raw.splitlines()
    seen = set()
    for position, line in enumerate(entries):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            if position == len(entries) - 1 and not raw.endswith("\n"):
                print("Recovery warning: ignored an incomplete final journal line")
                break
            raise ValueError(f"Invalid journal record at line {position + 1}")
        if not isinstance(entry, dict):
            raise ValueError("Invalid journal record")
        if "item_id" in entry:
            item = next((item for item in snapshot["items"] if item["id"] == entry["item_id"]), None)
            result = entry.get("result")
        else:
            item = snapshot["items"][position] if position < len(snapshot["items"]) else None
            result = entry
        if item is None or item["id"] in seen or not isinstance(result, dict):
            raise ValueError("Unknown or duplicate journal row")
        baseline = item["result"]
        if result.get("query") != baseline.get("query") or any(result.get(key) != baseline.get(key) for key in
                ("original_menu_text", "input_brewery", "input_beer", "input_abv", "input_style")):
            raise ValueError("Journal does not match the original menu identity")
        seen.add(item["id"])
        item["result"] = result
    return _validate_saved_rows(snapshot)


def continue_run(source: Path, *, min_score: float = DEFAULT_MIN_SCORE, debug: bool = False,
                 csv_requested: bool = False, recovery_menu: Optional[Path] = None) -> Path:
    snapshot = deepcopy(load_continuation(source, recovery_menu))
    pending = [item for item in snapshot["items"] if item["result"].get("status") in UNFINISHED]
    if not pending:
        raise ValueError("This run has no rate-limited or unattempted rows")
    inputs = [_search_input(item["result"]) for item in pending]
    # Create fresh metadata while preserving IDs, decisions and candidate additions.
    fresh = build_snapshot([item["result"] for item in snapshot["items"]], snapshot["report"]["title"])
    snapshot["report"] = fresh["report"]
    snapshot["created_at"] = fresh["created_at"]
    original_dir = source.expanduser().resolve()
    if not original_dir.is_dir():
        original_dir = original_dir.parent
    snapshot["continued_from"] = str(original_dir)
    output = original_dir.parent / (original_dir.name[:160] + "_continue_" + uuid4().hex)
    output.mkdir()
    save_snapshot(snapshot, output / "results.input.json")
    completed = False
    count = 0
    with debug_transcript(output, debug), (output / "results.partial.jsonl").open("x", encoding="utf-8") as journal:
        def checkpoint(result):
            nonlocal count
            item = pending[count]
            journal.write(json.dumps({"item_id": item["id"], "result": result}, ensure_ascii=False, allow_nan=False) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
            item["result"] = result
            count += 1
        try:
            with untappd_browser_page() as page:
                run_batch(page, inputs, min_score=min_score, debug=debug, on_result=checkpoint)
            completed = True
        finally:
            for item in pending[count:]:
                old = item["result"]
                reason = "Continuation interrupted before this row completed"
                item["result"] = unattempted_result(_search_input(old), reason)
            save_snapshot(snapshot, output / "results.json")
            results = [item["result"] for item in snapshot["items"]]
            (output / "results.html").write_text(render_html_report(results, snapshot["report"]["title"], snapshot["report"]["date"]), encoding="utf-8")
            if csv_requested:
                save_csv(results, str(output / "results.csv"))
            if completed and not any(result.get("status") in UNFINISHED for result in results):
                (output / "results.partial.jsonl").unlink()
                (output / "results.input.json").unlink()
            print(f"Run outputs: {output}")
    return output
