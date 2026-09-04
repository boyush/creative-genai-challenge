"""Filesystem-based checkpoint/state store. No DB, no server."""
import json
import time
from pathlib import Path

from src import config


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load(challenger_id: str) -> dict:
    path = config.state_path(challenger_id)
    if not path.exists():
        return {"challenger": challenger_id, "stages": {}, "updated_at": None}
    return json.loads(path.read_text())


def save(challenger_id: str, state: dict) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now()
    config.state_path(challenger_id).write_text(json.dumps(state, indent=2))


def mark(challenger_id: str, stage: str, status: str, **details) -> dict:
    state = load(challenger_id)
    state.setdefault("stages", {})[stage] = {
        "status": status,
        "ts": _now(),
        **details,
    }
    save(challenger_id, state)
    return state


def is_completed(state: dict, stage: str) -> bool:
    entry = state.get("stages", {}).get(stage)
    return bool(entry and entry.get("status") == "completed")


def stage_output_exists(state: dict, stage: str) -> bool:
    entry = state.get("stages", {}).get(stage, {})
    out = entry.get("output")
    if not out:
        return True  # stages with no file output are trivially "present"
    return Path(out).exists()
