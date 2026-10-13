"""Opt-in registration of new menus; never replace an existing entry."""
import json
import os
import tempfile
from pathlib import Path

from untap.identity import report_identity
from untap.snapshot import load_snapshot
from untap.refresh_config import config_defaults


def register_run(config: Path, run: Path) -> bool:
    config = config.expanduser().resolve()
    snapshot = load_snapshot(run / "results.json")
    if any(item["result"].get("status") in ("rate_limited", "not_attempted")
           or item["result"].get("batch_remaining") for item in snapshot["items"]):
        raise ValueError("Incomplete run: unattempted or rate-limited menu rows cannot be registered")
    title = report_identity(snapshot["report"]["title"])
    before = config.read_bytes() if config.exists() else None
    data = json.loads(before) if before is not None else {"reports": []}
    config_defaults(data)
    for entry in data["reports"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("source"), str):
            raise ValueError("Invalid refresh configuration entry")
        source = Path(entry["source"]).expanduser()
        if not source.is_absolute():
            source = config.parent / source
        snapshot_path = source / "results.json" if source.is_dir() else source
        try:
            existing = load_snapshot(snapshot_path)
        except FileNotFoundError:
            print(f"Registration warning: skipping missing source {source}. The stale configuration entry is unchanged.")
            continue
        if report_identity(existing["report"]["title"]) == title:
            print("Registration skipped: this menu already exists; its source, archive and selections are unchanged.")
            return False
    data["reports"].append({"source": os.path.relpath(run.resolve(), config.parent)})
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=config.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    try:
        if (config.read_bytes() if config.exists() else None) != before:
            raise ValueError("Configuration changed during registration; retry")
        temporary.replace(config)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Registered new menu in {config}. Add archive/selections settings there if needed.")
    return True


def register_run_safely(config: str, run: Path) -> None:
    try:
        register_run(Path(config), run)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Registration failed (run outputs are safe): {exc}")
