"""Central path/constants config for the creative-factory pipeline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INPUT_DIR = ROOT / "input"
ASSETS_DIR = ROOT / "assets"
ASSETS_EXTRACTED_DIR = ASSETS_DIR / "extracted"
ASSETS_GENERATED_DIR = ASSETS_DIR / "generated"
FINAL_DIR = ROOT / "final"
LOCALIZED_DIR = ROOT / "localized"
REPORTS_DIR = ROOT / "reports"
MANIFESTS_DIR = ROOT / "manifests"
EXPERIMENTS_DIR = MANIFESTS_DIR / "experiments"
WINNERS_DIR = MANIFESTS_DIR / "winners"
STATE_DIR = ROOT / "state"

WINNER_01 = INPUT_DIR / "winner_01.mp4"

FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"

TARGET_RESOLUTION = (1080, 1920)
TARGET_FPS = 30

STAGES = [
    "validate_inputs",
    "resolve_assets",
    "build_timeline",
    "render",
    "qa",
    "lineage",
]


def challenger_manifest_path(challenger_id: str) -> Path:
    return EXPERIMENTS_DIR / f"challenger_{challenger_id}.json"


def state_path(challenger_id: str) -> Path:
    return STATE_DIR / f"challenger_{challenger_id}.json"


def build_dir(challenger_id: str) -> Path:
    return ASSETS_GENERATED_DIR / f"challenger_{challenger_id}"


def final_output_path(challenger_id: str, locale: str = "EN") -> Path:
    return FINAL_DIR / f"{challenger_id}_{locale}.mp4"


def lineage_path(challenger_id: str) -> Path:
    return REPORTS_DIR / f"challenger_{challenger_id}_lineage.json"
