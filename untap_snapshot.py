"""Versioned, lossless run snapshots for offline report regeneration."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Sequence

from untap_types import MatchResult


FORMAT = "untap-results"
VERSION = 1


def build_snapshot(results: Sequence[MatchResult], title: str) -> Dict[str, Any]:
    """Assign occurrence-aware IDs from menu identity, not scores or row order."""
    occurrences: Dict[str, int] = {}
    items = []
    for result in results:
        identity = {key: result.get(key) for key in (
            "original_menu_text", "input_brewery", "input_beer",
            "input_abv", "input_style", "query",
        )}
        digest = hashlib.sha256(json.dumps(
            identity, ensure_ascii=False, sort_keys=True,
        ).encode("utf-8")).hexdigest()
        occurrences[digest] = occurrences.get(digest, 0) + 1
        items.append({"id": f"{digest}:{occurrences[digest]}", "result": result})
    now = datetime.now().astimezone()
    snapshot = {
        "format": FORMAT, "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report": {"title": title, "date": now.date().isoformat()},
        "items": items,
        "manual_decisions": [],
    }
    # Fail before any output is written if a result is not JSON-safe.
    return json.loads(json.dumps(snapshot, ensure_ascii=False, allow_nan=False))


def save_snapshot(snapshot: Dict[str, Any], path: Path) -> None:
    """Write a new snapshot, refusing to overwrite an existing one."""
    text = json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text + "\n")


def load_snapshot(path: Path) -> Dict[str, Any]:
    """Load supported snapshots; never guess at future schema versions."""
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict) or snapshot.get("format") != FORMAT or snapshot.get("version") != VERSION:
        raise ValueError("Unsupported results snapshot format or version")
    report = snapshot.get("report")
    if not isinstance(report, dict) or not all(isinstance(report.get(k), str) for k in ("title", "date")):
        raise ValueError("Invalid snapshot report metadata")
    items = snapshot.get("items")
    if not isinstance(items, list) or not isinstance(snapshot.get("manual_decisions"), list):
        raise ValueError("Invalid snapshot items or manual decisions")
    ids = set()
    for item in items:
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                or not item["id"] or item["id"] in ids
                or not isinstance(item.get("result"), dict)):
            raise ValueError("Invalid or duplicate snapshot item")
        ids.add(item["id"])
    return snapshot
