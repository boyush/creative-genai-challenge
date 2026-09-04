"""
Deterministic technical QA (ffprobe/ffmpeg), generalized from the checks
actually performed across the A/DE/FR/KO/B builds (see
scripts/localize_build.py::run_qa and the reports/A_*_lineage.json /
manifests/experiments/challenger_B.json "qa" blocks this generalizes).

Technical QA here answers "is this a well-formed deliverable" -- it cannot
and does not answer "is this a good ad". Perceptual/native-language/
creative QA is a human judgment call and is represented explicitly by
perceptual_qa_placeholder(), never computed automatically. Do not treat a
technical PASS as a creative approval.
"""
import subprocess
from pathlib import Path
from typing import Optional

DECODE_TIMEOUT = 180
PROBE_TIMEOUT = 30


class QAError(RuntimeError):
    pass


def _probe(path: Path, *args: str) -> str:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", *args, str(path)],
                            capture_output=True, text=True, timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise QAError(f"ffprobe timed out on {path}")
    return r.stdout.strip()


def technical_qa(path: Path, *, expected: Optional[dict] = None) -> dict:
    """expected (all optional) may contain:
      resolution            -- ffprobe csv form, e.g. "1080,1920"
      video_codec           -- e.g. "h264"
      audio_codec           -- e.g. "aac"
      fps                   -- ffprobe r_frame_rate form, e.g. "30/1"
      min_duration_seconds / max_duration_seconds

    Always includes the fixed checks (exists, non-zero, has streams, clean
    decode); adds a `_matches`/`_ok` check per expected key supplied.
    `pass` is True only if every check (fixed + expected) is True.
    """
    path = Path(path)
    result = {"path": str(path)}

    exists = path.exists()
    non_zero = exists and path.stat().st_size > 0
    result["file_exists"] = exists
    result["non_zero_size"] = non_zero
    if not non_zero:
        result["checks"] = {"file_exists": exists, "non_zero_size": non_zero}
        result["pass"] = False
        return result

    vcodec = _probe(path, "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1")
    acodec = _probe(path, "-select_streams", "a:0", "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1")
    res = _probe(path, "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0")
    fps = _probe(path, "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "default=nw=1:nk=1")
    dur_raw = _probe(path, "-show_entries", "format=duration", "-of", "default=nw=1:nk=1")
    duration = float(dur_raw) if dur_raw else 0.0

    try:
        decode = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
                                 capture_output=True, text=True, timeout=DECODE_TIMEOUT)
        decode_clean = decode.returncode == 0 and not decode.stderr.strip()
        decode_stderr = "" if decode_clean else decode.stderr[-500:]
    except subprocess.TimeoutExpired:
        decode_clean = False
        decode_stderr = f"decode timed out after {DECODE_TIMEOUT}s"

    result.update({
        "duration_seconds": duration,
        "resolution": res,
        "video_codec": vcodec,
        "audio_codec": acodec,
        "audio_present": bool(acodec),
        "fps": fps,
        "full_decode_clean": decode_clean,
        "full_decode_stderr": decode_stderr,
    })

    checks = {
        "file_exists": exists,
        "non_zero_size": non_zero,
        "has_video_stream": bool(vcodec),
        "has_audio_stream": bool(acodec),
        "full_decode_clean": decode_clean,
    }

    expected = expected or {}
    if "resolution" in expected:
        checks["resolution_matches"] = (res == expected["resolution"])
    if "video_codec" in expected:
        checks["video_codec_matches"] = (vcodec == expected["video_codec"])
    if "audio_codec" in expected:
        checks["audio_codec_matches"] = (acodec == expected["audio_codec"])
    if "fps" in expected:
        checks["fps_matches"] = (fps == expected["fps"])
    if "min_duration_seconds" in expected:
        checks["duration_min_ok"] = duration >= expected["min_duration_seconds"]
    if "max_duration_seconds" in expected:
        checks["duration_max_ok"] = duration <= expected["max_duration_seconds"]

    result["checks"] = checks
    result["pass"] = all(checks.values())
    return result


def perceptual_qa_placeholder(note: str = "") -> dict:
    """Explicitly separate from technical_qa(). Never returns a computed
    pass/fail -- native-language accuracy, persuasion-architecture
    preservation, and creative quality are human judgment calls (see every
    reports/A_*_lineage.json 'human_review_decision' for how this was
    actually done on this project)."""
    return {
        "status": "requires_human_review",
        "automated": False,
        "note": note or (
            "Perceptual/creative/native-language QA must be performed by a "
            "human reviewer. This pipeline does not compute a pass/fail "
            "for creative quality."
        ),
    }


def run_qa(path: Path, *, expected: Optional[dict] = None, perceptual_note: str = "") -> dict:
    """Top-level entrypoint: technical (automated) + perceptual (explicitly
    not automated) side by side, never merged into one verdict."""
    return {
        "technical": technical_qa(path, expected=expected),
        "perceptual": perceptual_qa_placeholder(perceptual_note),
    }
