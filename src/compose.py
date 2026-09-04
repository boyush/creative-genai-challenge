"""
Deterministic composition: scene/segment manifest -> rendered MP4.

Generalizes the trim/hold/caption-overlay/concat pipeline already proven
during the Challenger A hook build, the DE/FR/KO localization runs
(scripts/localize_build.py), and Challenger B's generated-hook + real-proof
composition. Takes an explicit scene manifest (see
src/manifest.py::load_scene_manifest) -- no challenger-specific branching
lives here; a manifest is data, not code.

Scene manifest shape (JSON):
{
  "output": "final/<challenger>_<locale>.mp4",
  "segments": [
    {"id": "...", "kind": "source", "source": "input/winner_01.mp4",
     "in": 4.8, "out": 59.0},
    {"id": "...", "kind": "generated",
     "generation": {"cache_path": "...", "provider": "fal.ai",
                     "endpoint_id": "...", "prompt": "...",
                     "input_params": {...}}}
  ]
}

Per-segment optional fields:
  caption          -- text to burn in (drawbox+overlay, PIL-rendered PNG)
  hold_to_duration -- freeze-extend the trimmed clip to this length
  audio            -- "source" (default, passthrough) | "mute" | a path to
                       a WAV to use instead of the segment's own audio

Every rendered per-segment clip always carries both a video and an audio
stream (silence is synthesized for "mute" segments) so the final concat is
safe regardless of how the "generated" vs "source" kinds are mixed.

Asset resolution for "generated" segments is cache-first via
src/generate.py: a live provider call only happens when the caller passes
allow_paid_call=True *and* no cached asset exists at generation.cache_path.
Real UI/payment/earnings proof must only ever appear via "source" segments
(CLAUDE.md rule #4) -- this module does not police that; the scene manifest
authoring is where that policy is enforced.
"""
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from src import config, generate, manifest

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
SHORT_TIMEOUT = 60
LONG_TIMEOUT = 180


class ComposeError(RuntimeError):
    pass


def _run(cmd: list[str], timeout: int = SHORT_TIMEOUT) -> None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ComposeError(f"ffmpeg timed out after {timeout}s: {' '.join(cmd)}")
    if r.returncode != 0:
        raise ComposeError(f"ffmpeg failed: {' '.join(cmd)}\nSTDERR: {r.stderr[-3000:]}")


def _ffprobe_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=30, check=True,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        raise ComposeError(f"ffprobe failed on {path}: {e}")
    return float(r.stdout.strip())


def _make_caption_png(text: str, out_path: Path, max_width_px=1000, fontsize=58,
                       stroke=5, line_gap=12, canvas_w=1080, canvas_h=440) -> Path:
    """Same layout/proven look as scripts/localize_build.py::make_caption_png,
    generalized (no locale/challenger-specific paths)."""
    font = ImageFont.truetype(FONT_PATH, fontsize)
    tmp_img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp_img)

    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        bbox = d.textbbox((0, 0), trial, font=font, stroke_width=stroke)
        if bbox[2] - bbox[0] <= max_width_px or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > 3:
        return _make_caption_png(text, out_path, max_width_px, fontsize - 6, stroke, line_gap, canvas_w, canvas_h)

    sizes = [d.textbbox((0, 0), l, font=font, stroke_width=stroke) for l in lines]
    heights = [b[3] - b[1] for b in sizes]
    total_h = sum(heights) + line_gap * (len(lines) - 1)
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = (canvas_h - total_h) // 2
    for line, bbox in zip(lines, sizes):
        w = bbox[2] - bbox[0]
        x = (canvas_w - w) // 2
        draw.text((x - bbox[0], y - bbox[1]), line, font=font, fill=(255, 255, 255, 255),
                   stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        y += (bbox[3] - bbox[1]) + line_gap
    img.save(out_path)
    return out_path


def _resolve_segment_source(seg: dict, *, allow_paid_call: bool) -> tuple[Path, float, float, str]:
    """Returns (video_path, in_ts, out_ts, resolution_kind) for one segment
    spec. resolution_kind is "source" | "cache" | "provider" for lineage."""
    if seg["kind"] == "source":
        path = Path(seg["source"])
        if not path.exists():
            raise ComposeError(f"segment {seg['id']!r}: source not found: {path}")
        return path, float(seg["in"]), float(seg["out"]), "source"
    elif seg["kind"] == "generated":
        asset = generate.request_generated_segment(seg, allow_paid_call=allow_paid_call)
        dur = _ffprobe_duration(asset.path)
        in_ts = float(seg.get("in", 0.0))
        out_ts = float(seg.get("out", dur))
        return asset.path, in_ts, out_ts, asset.source
    raise ComposeError(f"segment {seg['id']!r}: unknown kind {seg['kind']!r}")


def _build_segment_clip(seg: dict, video_path: Path, in_ts: float, out_ts: float,
                         work_dir: Path) -> Path:
    span = round(out_ts - in_ts, 3)
    if span <= 0:
        raise ComposeError(f"segment {seg['id']!r}: non-positive duration ({span}s)")
    hold_to = seg.get("hold_to_duration")
    caption = seg.get("caption")
    audio_mode = seg.get("audio", "source")

    # Every intermediate clip always gets both a video AND an audio stream
    # (silence synthesized for "mute") -- keeps the final concat safe no
    # matter how "source"/"generated"/muted segments are mixed.
    trimmed = work_dir / f"{seg['id']}_trim.mp4"
    cmd = ["ffmpeg", "-y", "-ss", f"{in_ts:.3f}", "-i", str(video_path), "-t", f"{span:.3f}"]
    if audio_mode == "mute":
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        cmd += ["-map", "0:v", "-map", "1:a"]
    else:
        cmd += ["-map", "0:v", "-map", "0:a"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(config.TARGET_FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-shortest", str(trimmed), "-loglevel", "error"]
    _run(cmd, timeout=LONG_TIMEOUT)

    video_stage = trimmed
    target_dur = float(hold_to) if hold_to else span
    if hold_to and target_dur > span + 0.02:
        held = work_dir / f"{seg['id']}_held.mp4"
        hold_secs = round(target_dur - span, 3)
        _run(["ffmpeg", "-y", "-i", str(trimmed),
              "-vf", f"tpad=stop_mode=clone:stop_duration={hold_secs:.3f}",
              "-af", f"apad=pad_dur={hold_secs:.3f}",
              "-t", f"{target_dur:.3f}",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(config.TARGET_FPS),
              "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
              str(held), "-loglevel", "error"], timeout=LONG_TIMEOUT)
        video_stage = held

    if isinstance(audio_mode, str) and audio_mode not in ("source", "mute"):
        external_wav = Path(audio_mode)
        if not external_wav.exists():
            raise ComposeError(f"segment {seg['id']!r}: audio override not found: {external_wav}")
        muxed = work_dir / f"{seg['id']}_audio.mp4"
        _run(["ffmpeg", "-y", "-i", str(video_stage), "-i", str(external_wav),
              "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
              "-b:a", "192k", "-ar", "48000", "-ac", "2", "-shortest",
              str(muxed), "-loglevel", "error"], timeout=LONG_TIMEOUT)
        video_stage = muxed

    if not caption:
        return video_stage

    cap_png = work_dir / f"{seg['id']}_cap.png"
    _make_caption_png(caption, cap_png)
    captioned = work_dir / f"{seg['id']}_final.mp4"
    duration = _ffprobe_duration(video_stage)
    filt = ("[0:v]drawbox=x=20:y=1090:w=1040:h=400:color=black@1:t=fill[bg];"
            "[bg][1:v]overlay=x=0:y=1110[v]")
    _run(["ffmpeg", "-y", "-i", str(video_stage), "-loop", "1", "-i", str(cap_png),
          "-filter_complex", filt, "-map", "[v]", "-map", "0:a",
          "-t", f"{duration:.3f}", "-shortest",
          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(config.TARGET_FPS),
          "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
          str(captioned), "-loglevel", "error"], timeout=LONG_TIMEOUT)
    return captioned


def compose(scene_manifest_path: Path, *, output_override: Optional[Path] = None,
            allow_paid_call: bool = False) -> dict:
    """Mandatory validation boundary (src/manifest.py::load_scene_manifest)
    runs first and raises ManifestError before any generation/render is
    attempted -- invalid/malformed manifests fail before execution, never
    get silently repaired. Returns a dict recording exactly what was
    resolved per segment (source / cache / provider), which feeds directly
    into lineage."""
    data = manifest.load_scene_manifest(Path(scene_manifest_path))

    output_path = Path(output_override) if output_override else config.ROOT / data["output"]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lineage_segments = []
    with tempfile.TemporaryDirectory(prefix="compose_") as tmp:
        work_dir = Path(tmp)
        clip_paths = []
        for seg in data["segments"]:
            video_path, in_ts, out_ts, resolution_kind = _resolve_segment_source(
                seg, allow_paid_call=allow_paid_call
            )
            clip = _build_segment_clip(seg, video_path, in_ts, out_ts, work_dir)
            clip_paths.append(clip)
            lineage_segments.append({
                "id": seg["id"],
                "kind": seg["kind"],
                "resolved_via": resolution_kind,
                "resolved_source": str(video_path),
                "in": in_ts,
                "out": out_ts,
                "duration": round(out_ts - in_ts, 3),
            })

        concat_list = work_dir / "concat_list.txt"
        concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in clip_paths))
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "main", "-level", "4.1",
              "-r", str(config.TARGET_FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
              "-ac", "2", str(output_path), "-loglevel", "error"], timeout=LONG_TIMEOUT)

    return {
        "manifest": str(scene_manifest_path),
        "output": str(output_path),
        "allow_paid_call": allow_paid_call,
        "segments": lineage_segments,
        "paid_calls_made": sum(1 for s in lineage_segments if s["resolved_via"] == "provider"),
    }
