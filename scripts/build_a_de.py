"""
Build final/A_DE.mp4 from final/A_EN.mp4 + existing checkpoint artifacts:
  reports/A_EN_transcript.json
  reports/A_DE_translation.json
  reports/A_EN_speaker_visual_analysis.json
  reports/A_DE_dub_manifest.json          (raw per-segment TTS, already generated)
  assets/generated/challenger_A/de/reference_voice_url_fal.json

Per-segment pipeline (23 transcript segments covering 0-50.10s of A_EN):
  1. time-align the raw TTS clip to (clamped) target duration via atempo
  2. build a caption PNG (German text) in the same visual style as A_EN
  3. build the segment's video:
       - lip-sync candidates (ids 2,7,14,20,21): fal-ai/sync-lipsync/v2/pro
         on the original A_EN video subclip + the aligned German audio
       - everything else: original A_EN video subclip, frozen-extended or
         trimmed (never sped up/slowed -- "authentic source asset") to the
         aligned audio's duration
  4. drawbox-cover the original caption + overlay the German caption PNG
  5. mux with the aligned audio
Then concatenate all 23 segment clips + the untouched CTA tail (50.10s to
end of A_EN, no dialogue there) into final/A_DE.mp4.
"""
import sys, json, subprocess, shutil
sys.path.insert(0, '.')
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from src import localize

ROOT = Path('.')
DE_DIR = ROOT / 'assets/generated/challenger_A/de'
SEG_DIR = DE_DIR / 'segments_de'
SEG_DIR.mkdir(parents=True, exist_ok=True)
DUB_DIR = DE_DIR / 'dub'
LIPSYNC_DIR = DE_DIR / 'lipsync'
LIPSYNC_DIR.mkdir(parents=True, exist_ok=True)
CAPTION_DIR = DE_DIR / 'captions'
CAPTION_DIR.mkdir(parents=True, exist_ok=True)

A_EN = ROOT / 'final/A_EN.mp4'
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Black.ttf"

LIPSYNC_IDS = {2, 7, 14, 20, 21}
ATEMPO_MIN, ATEMPO_MAX = 0.85, 1.95

STATE_PATH = ROOT / 'reports/A_DE_build_state.json'


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"segments": {}}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def run(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"cmd timed out after {timeout}s: {' '.join(cmd)}")
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\nSTDERR: {r.stderr[-3000:]}")
    return r


def ffprobe_dur(p: Path) -> float:
    return localize.ffprobe_duration(p)


def make_caption_png(text: str, out_path: Path, max_width_px=1000, fontsize=58,
                      stroke=5, line_gap=12, canvas_w=1080, canvas_h=440):
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
        # shrink font iteratively if too many lines
        return make_caption_png(text, out_path, max_width_px, fontsize - 6, stroke, line_gap, canvas_w, canvas_h)

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


def align_audio(raw_path: Path, target_duration: float, out_path: Path) -> float:
    raw_dur = ffprobe_dur(raw_path)
    ratio = raw_dur / target_duration
    factor = max(ATEMPO_MIN, min(ATEMPO_MAX, ratio))
    run(["ffmpeg", "-y", "-i", str(raw_path), "-af", f"atempo={factor:.4f}",
         "-ar", "44100", "-ac", "1", str(out_path), "-loglevel", "error"])
    return ffprobe_dur(out_path)


def build_nonlipsync_video(start, span, target_dur, out_path: Path):
    """Original A_EN video pixels for [start, start+span]; frozen-extend or
    trim (never retimed) to target_dur so it never deviates from authentic
    source frames."""
    tmp = out_path.with_suffix('.raw.mp4')
    run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(A_EN), "-t", f"{span:.3f}",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
         str(tmp), "-loglevel", "error"])
    actual = ffprobe_dur(tmp)
    if target_dur <= actual + 0.02:
        run(["ffmpeg", "-y", "-i", str(tmp), "-t", f"{target_dur:.3f}", "-an",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
             str(out_path), "-loglevel", "error"])
    else:
        hold = target_dur - actual
        run(["ffmpeg", "-y", "-i", str(tmp), "-vf",
             f"tpad=stop_mode=clone:stop_duration={hold:.3f}", "-an",
             "-t", f"{target_dur:.3f}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
             str(out_path), "-loglevel", "error"])
    tmp.unlink(missing_ok=True)


def caption_over_video(video_in: Path, caption_png: Path, out_path: Path, with_audio: Path | None):
    # video_in is always a finite, pre-trimmed clip; the caption PNG is
    # -loop 1'd (infinite). Bound the output explicitly to video_in's probed
    # duration -- do not rely on -shortest, which is a no-op here when only
    # a single ([v]) output stream is mapped and previously let this run
    # unbounded against the looped image input.
    duration = ffprobe_dur(video_in)
    filt = ("[0:v]drawbox=x=20:y=1090:w=1040:h=400:color=black@1:t=fill[bg];"
            "[bg][1:v]overlay=x=0:y=1110[v]")
    cmd = ["ffmpeg", "-y", "-i", str(video_in), "-loop", "1", "-i", str(caption_png)]
    if with_audio is not None:
        cmd += ["-i", str(with_audio)]
    cmd += ["-filter_complex", filt, "-map", "[v]"]
    if with_audio is not None:
        cmd += ["-map", "2:a"]
    cmd += ["-t", f"{duration:.3f}", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30"]
    if with_audio is not None:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd += [str(out_path), "-loglevel", "error"]
    run(cmd)


def process_segment(seg, ref_url):
    sid = seg['id']
    start, end = seg['start'], seg['end']
    span = end - start
    de_text = seg['de_text']

    final_clip = SEG_DIR / f"seg_{sid:02d}_final.mp4"
    if final_clip.exists():
        print(f"[{sid}] already built, skip")
        return str(final_clip)

    raw_wav = DUB_DIR / f"seg_{sid:02d}_raw.wav"
    aligned_wav = DUB_DIR / f"seg_{sid:02d}_aligned.wav"
    aligned_dur = align_audio(raw_wav, span, aligned_wav)
    print(f"[{sid}] aligned audio -> {aligned_dur:.2f}s (orig span {span:.2f}s)")

    cap_png = CAPTION_DIR / f"cap_{sid:02d}.png"
    make_caption_png(de_text, cap_png)

    if sid in LIPSYNC_IDS:
        raw_video_clip = LIPSYNC_DIR / f"seg_{sid:02d}_srcvideo.mp4"
        if not raw_video_clip.exists():
            run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(A_EN), "-t", f"{span:.3f}",
                 "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                 str(raw_video_clip), "-loglevel", "error"])
        lipsynced = LIPSYNC_DIR / f"seg_{sid:02d}_lipsynced.mp4"
        if not lipsynced.exists():
            video_url = localize.fal_upload_file(raw_video_clip, "video/mp4")
            audio_url = localize.fal_upload_file(aligned_wav, "audio/wav")
            print(f"[{sid}] calling fal lipsync ...")
            out_bytes = None
            for attempt in range(3):
                try:
                    out_bytes = localize.lipsync_clip(video_url, audio_url)
                    break
                except Exception as e:
                    print(f"  lipsync attempt {attempt+1} failed: {e}")
            if out_bytes is None:
                raise RuntimeError(f"segment {sid} lipsync failed after retries")
            lipsynced.write_bytes(out_bytes)
            print(f"[{sid}] lipsync done -> {ffprobe_dur(lipsynced):.2f}s")
        # caption over lipsynced video; lipsynced video already carries the
        # aligned German audio (sync/lipsync-2 conforms video to it)
        caption_over_video(lipsynced, cap_png, final_clip, with_audio=None)
        # lipsynced clip has its own audio track; re-mux with it explicitly
        tmp_v = final_clip.with_suffix('.videoonly.mp4')
        final_clip.rename(tmp_v)
        run(["ffmpeg", "-y", "-i", str(tmp_v), "-i", str(lipsynced), "-map", "0:v", "-map", "1:a",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             "-shortest", str(final_clip), "-loglevel", "error"])
        tmp_v.unlink(missing_ok=True)
    else:
        nonlip_video = SEG_DIR / f"seg_{sid:02d}_video.mp4"
        build_nonlipsync_video(start, span, aligned_dur, nonlip_video)
        caption_over_video(nonlip_video, cap_png, final_clip, with_audio=aligned_wav)
        nonlip_video.unlink(missing_ok=True)

    print(f"[{sid}] final clip -> {ffprobe_dur(final_clip):.2f}s")
    return str(final_clip)


def main():
    translation = json.loads(Path('reports/A_DE_translation.json').read_text())
    ref_url = json.loads((DE_DIR / 'reference_voice_url_fal.json').read_text())['reference_voice_url_fal']

    state = load_state()
    clip_paths = []
    for seg in translation['segments']:
        sid = seg['id']
        key = str(sid)
        if key in state['segments'] and Path(state['segments'][key]).exists():
            clip_paths.append(state['segments'][key])
            continue
        path = process_segment(seg, ref_url)
        state['segments'][key] = path
        save_state(state)
        clip_paths.append(path)

    # tail: unchanged CTA end card, no dialogue, from end of last transcript
    # segment through the end of A_EN
    last_end = translation['segments'][-1]['end']
    en_total = ffprobe_dur(A_EN)
    tail_clip = SEG_DIR / 'tail_cta.mp4'
    if not tail_clip.exists():
        run(["ffmpeg", "-y", "-ss", f"{last_end:.3f}", "-i", str(A_EN),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             str(tail_clip), "-loglevel", "error"], timeout=120)
    clip_paths.append(str(tail_clip))

    concat_list = SEG_DIR / 'concat_list.txt'
    concat_list.write_text("\n".join(f"file '{Path(p).resolve()}'" for p in clip_paths))

    Path('final').mkdir(exist_ok=True)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "main", "-level", "4.1", "-r", "30",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
         "final/A_DE.mp4", "-loglevel", "error"], timeout=180)
    print("DONE -> final/A_DE.mp4, duration:", ffprobe_dur(Path('final/A_DE.mp4')))


if __name__ == '__main__':
    main()
