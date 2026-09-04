"""Load and validate challenger + source-inventory manifests."""
import json
from pathlib import Path

from src import config


class ManifestError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    if not path.exists():
        raise ManifestError(f"missing required file: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ManifestError(f"invalid JSON in {path}: {e}")


def load_challenger(challenger_id: str) -> dict:
    path = config.challenger_manifest_path(challenger_id)
    data = load_json(path)
    required = ["experiment_id", "parent", "primary_variable", "hook", "output"]
    missing = [k for k in required if k not in data]
    if missing:
        raise ManifestError(f"{path} missing required keys: {missing}")
    return data


def load_inventory() -> dict:
    path = config.REPORTS_DIR / "winner_01_asset_inventory.json"
    data = load_json(path)
    if "candidate_segments" not in data:
        raise ManifestError(f"{path} missing 'candidate_segments'")
    return data


def load_transcript_if_present() -> dict | None:
    path = config.REPORTS_DIR / "winner_01_transcript.json"
    if not path.exists():
        return None
    return load_json(path)


def validate_source_video(challenger: dict) -> Path:
    parent = challenger["parent"]
    src = config.INPUT_DIR / f"{parent}.mp4"
    if not src.exists():
        raise ManifestError(f"source video for parent '{parent}' not found: {src}")
    return src


SCENE_REQUIRED_KEYS = ["output", "segments"]
SEGMENT_REQUIRED_KEYS = ["id", "kind"]
SEGMENT_VALID_KINDS = ("source", "generated")


def load_scene_manifest(path: Path) -> dict:
    """Generic (non-challenger-specific) scene/segment manifest, consumed
    by src/compose.py. This is a MANDATORY boundary: invalid JSON or a
    malformed schema raises ManifestError here, before any asset
    resolution, generation, or render is attempted -- nothing downstream
    silently repairs a bad manifest. This is what would have caught the
    Challenger B manifest JSON-syntax error discovered by hand during that
    build (a stray key inside an array), instead of failing at an
    arbitrary later json.load() call.
    """
    data = load_json(path)

    missing = [k for k in SCENE_REQUIRED_KEYS if k not in data]
    if missing:
        raise ManifestError(f"{path} missing required keys: {missing}")

    segments = data["segments"]
    if not isinstance(segments, list) or not segments:
        raise ManifestError(f"{path}: 'segments' must be a non-empty list")

    seen_ids = set()
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            raise ManifestError(f"{path}: segments[{i}] must be an object, got {type(seg).__name__}")
        missing = [k for k in SEGMENT_REQUIRED_KEYS if k not in seg]
        if missing:
            raise ManifestError(f"{path}: segments[{i}] missing required keys: {missing}")
        if seg["kind"] not in SEGMENT_VALID_KINDS:
            raise ManifestError(
                f"{path}: segments[{i}] has invalid kind {seg['kind']!r}; "
                f"expected one of {SEGMENT_VALID_KINDS}"
            )
        if seg["id"] in seen_ids:
            raise ManifestError(f"{path}: duplicate segment id {seg['id']!r}")
        seen_ids.add(seg["id"])

        if seg["kind"] == "source":
            missing = [k for k in ("source", "in", "out") if k not in seg]
            if missing:
                raise ManifestError(f"{path}: segments[{i}] (kind=source) missing keys: {missing}")
            if float(seg["out"]) <= float(seg["in"]):
                raise ManifestError(f"{path}: segments[{i}] has non-positive duration (in={seg['in']}, out={seg['out']})")
        elif seg["kind"] == "generated":
            gen = seg.get("generation")
            if not isinstance(gen, dict) or "cache_path" not in gen:
                raise ManifestError(
                    f"{path}: segments[{i}] (kind=generated) missing 'generation.cache_path'"
                )

    return data
