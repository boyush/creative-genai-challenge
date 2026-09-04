"""
ONE corrected representative German segment (id=14, a lip-synced,
visible-speaking segment) for human review of the A_DE quality-QA fixes:

  A. natural pacing: atempo capped at a small, natural range (0.9-1.15x)
     instead of the old 0.85-1.95x; video timing expands to match, never
     forcing audio into the exact original English span.
  B. no English/German overlap: unchanged from the existing (already
     correct) structural design -- source video is extracted with -an
     before lip-sync/mux, audio always comes solely from the localized
     track. (Documented in the diagnostic report, not re-verified here.)
  C. pronunciation: cfg_scale=0.0 (fal-ai/chatterbox/text-to-speech's own
     documented setting for cross-lingual "language transfer", to mitigate
     accent inheritance from the English reference voice) instead of 0.5.
  D. lip-sync runs against this new, natural-paced aligned audio, not the
     old aggressively-compressed dub.

Does NOT touch final/A_DE.mp4, reports/A_DE_build_state.json, or any other
cached A_DE segment. Output goes to a separate qc_fix_sample/ directory for
review only.
"""
import sys, json, subprocess
sys.path.insert(0, '.')
from pathlib import Path
from src import localize

ROOT = Path('.')
DE_DIR = ROOT / 'assets/generated/challenger_A/de'
A_EN = ROOT / 'final/A_EN.mp4'
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
OUT_DIR = DE_DIR / 'qc_fix_sample'
OUT_DIR.mkdir(parents=True, exist_ok=True)

SID = 14
NATURAL_ATEMPO_MIN, NATURAL_ATEMPO_MAX = 0.9, 1.15


def run(cmd, timeout=60):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\nSTDERR: {r.stderr[-2000:]}")
    return r


def ffprobe_dur(p: Path) -> float:
    return localize.ffprobe_duration(p)


def main():
    translation = json.loads((ROOT / 'reports/A_DE_translation.json').read_text())
    seg = next(s for s in translation['segments'] if s['id'] == SID)
    start, end = seg['start'], seg['end']
    span = end - start
    de_text = seg['de_text']
    ref_url = json.loads((DE_DIR / 'reference_voice_url_fal.json').read_text())['reference_voice_url_fal']

    print(f"[{SID}] text: {de_text!r}  target_span={span:.2f}s")

    # --- C: regenerate raw TTS with cfg_scale=0.0 (was 0.5) ---
    raw_wav = OUT_DIR / f"seg_{SID:02d}_raw_cfg0.wav"
    print(f"[{SID}] regenerating TTS with cfg_scale=0.0 (was 0.5) ...")
    result = localize._fal_run(
        localize.FAL_TTS_MODEL,
        {
            "text": de_text,
            "voice": ref_url,
            "custom_audio_language": "german",
            "cfg_scale": 0.0,
            "temperature": 0.7,
            "exaggeration": 0.5,
        },
    )
    audio_url = result["audio"]["url"]
    import requests
    r = requests.get(audio_url, timeout=120)
    r.raise_for_status()
    raw_wav.write_bytes(r.content)
    raw_dur = ffprobe_dur(raw_wav)
    print(f"[{SID}] new raw TTS duration: {raw_dur:.2f}s (old raw was 3.14s, target span {span:.2f}s)")

    # --- A: natural-pace alignment (no aggressive compression) ---
    ratio = raw_dur / span
    factor = max(NATURAL_ATEMPO_MIN, min(NATURAL_ATEMPO_MAX, ratio))
    aligned_wav = OUT_DIR / f"seg_{SID:02d}_aligned_natural.wav"
    run(["ffmpeg", "-y", "-i", str(raw_wav), "-af", f"atempo={factor:.4f}",
         "-ar", "44100", "-ac", "1", str(aligned_wav), "-loglevel", "error"])
    aligned_dur = ffprobe_dur(aligned_wav)
    print(f"[{SID}] natural-pace atempo factor={factor:.3f} (old was 1.427) -> aligned duration {aligned_dur:.2f}s "
          f"(video will expand from {span:.2f}s to match, not force-compress audio)")

    # --- D: lip-sync against the new natural-paced audio ---
    raw_video_clip = DE_DIR / 'lipsync' / f"seg_{SID:02d}_srcvideo.mp4"  # reused, already cached
    assert raw_video_clip.exists(), "expected cached silent source clip"
    print(f"[{SID}] lip-syncing against natural-paced audio (reusing cached silent source clip, no re-extraction)...")
    video_url = localize.fal_upload_file(raw_video_clip, "video/mp4")
    audio_url2 = localize.fal_upload_file(aligned_wav, "audio/wav")
    out_bytes = localize.lipsync_clip(video_url, audio_url2, timeout_s=180)
    lipsynced = OUT_DIR / f"seg_{SID:02d}_lipsynced_corrected.mp4"
    lipsynced.write_bytes(out_bytes)
    print(f"[{SID}] corrected lip-sync done -> {ffprobe_dur(lipsynced):.2f}s")

    # --- composite: caption overlay (bounded-duration) + remux, same as the fixed build_a_de.py path ---
    cap_png = DE_DIR / 'captions' / f"cap_{SID:02d}.png"  # already exists/cached
    assert cap_png.exists()
    final_clip = OUT_DIR / f"seg_{SID:02d}_REVIEW.mp4"
    duration = ffprobe_dur(lipsynced)
    filt = ("[0:v]drawbox=x=20:y=1090:w=1040:h=400:color=black@1:t=fill[bg];"
            "[bg][1:v]overlay=x=0:y=1110[v]")
    run(["ffmpeg", "-y", "-i", str(lipsynced), "-loop", "1", "-i", str(cap_png),
         "-filter_complex", filt, "-map", "[v]", "-t", f"{duration:.3f}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-an",
         str(final_clip) + ".video.mp4", "-loglevel", "error"])
    run(["ffmpeg", "-y", "-i", str(final_clip) + ".video.mp4", "-i", str(lipsynced),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-ar", "48000", "-ac", "2", "-shortest", str(final_clip), "-loglevel", "error"])
    Path(str(final_clip) + ".video.mp4").unlink(missing_ok=True)

    print(f"\nREVIEW: {final_clip}  duration={ffprobe_dur(final_clip):.2f}s "
          f"(original A_EN span for this line was {span:.2f}s)")


if __name__ == '__main__':
    main()
