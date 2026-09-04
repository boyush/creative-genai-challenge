"""
Generalized, resumable Challenger A localization runner. Reuses the proven
A_DE implementation (scripts/build_a_de.py) end-to-end for any locale:
  - reuses final/A_EN.mp4 + reports/A_EN_transcript.json (no retranscription)
  - reuses reports/A_EN_speaker_visual_analysis.json to derive lip-sync
    ranges (same rule the A_DE build used: onscreen_mouth_speaking_this_line
    AND visual_content == "creator_talking_head" -- this reproduces
    {2,7,14,20,21} for Challenger A, verified against build_a_de.py's
    hardcoded LIPSYNC_IDS)
  - reuses the same fal-hosted reference voice URL as A_DE
    (assets/generated/challenger_A/de/reference_voice_url_fal.json)
  - reuses the fixed bounded-duration FFmpeg caption/compose pipeline
    (caption_over_video below is the same -t-bounded fix applied to
    scripts/build_a_de.py)

Throughput optimizations added on top of the proven per-segment logic (no
architecture change):
  - bounded concurrency for independent fal.ai TTS jobs (default 4)
  - bounded concurrency for independent fal.ai lip-sync jobs (default 2)
  - per-segment artifacts are checked for existence before any paid call
    ("cache every successful paid result before proceeding")
  - hard timeouts: 60s for short local ffmpeg ops, 120-180s for the two
    whole-clip local ops (tail extraction, final concat), 180s per fal.ai
    call (fal exposes no partial-progress signal, so this is enforced as
    an overall per-call cap -- consistent with observed real completion
    times of 1-3 min per call in the A_DE run)
  - state is written to a locale-scoped file after every successful
    segment (reports/A_<LOCALE>_build_state.json), never to the shared
    state/challenger_A.json -- that lets two locales run as separate
    concurrent processes with zero shared-state write collisions

Usage:
  python3 scripts/localize_build.py fr French
  python3 scripts/localize_build.py ko Korean
"""
import sys, json, subprocess, threading
sys.path.insert(0, '.')
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageDraw, ImageFont

from src import localize

ROOT = Path('.')
A_EN = ROOT / 'final/A_EN.mp4'
REF_VOICE_URL_FILE = ROOT / 'assets/generated/challenger_A/de/reference_voice_url_fal.json'
EN_TRANSCRIPT = ROOT / 'reports/A_EN_transcript.json'
SPEAKER_ANALYSIS = ROOT / 'reports/A_EN_speaker_visual_analysis.json'
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
ATEMPO_MIN, ATEMPO_MAX = 0.85, 1.95

TTS_WORKERS = 4
LIPSYNC_WORKERS = 2
SHORT_TIMEOUT = 60
LONG_TIMEOUT = 180
FAL_TIMEOUT = 180


def run(cmd, timeout=SHORT_TIMEOUT):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"cmd timed out after {timeout}s: {' '.join(cmd)}")
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\nSTDERR: {r.stderr[-3000:]}")
    return r


def ffprobe_dur(p: Path) -> float:
    return localize.ffprobe_duration(p)


def compute_lipsync_ids() -> set:
    analysis = json.loads(SPEAKER_ANALYSIS.read_text())
    return {
        c['id'] for c in analysis['classifications']
        if c.get('onscreen_mouth_speaking_this_line') and c.get('visual_content') == 'creator_talking_head'
    }


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


def caption_over_video(video_in: Path, caption_png: Path, out_path: Path, with_audio):
    # Bounded-duration fix (same as scripts/build_a_de.py): video_in is
    # always finite, the caption PNG is -loop 1'd (infinite) -- bound the
    # output explicitly to video_in's probed duration instead of relying
    # on -shortest, which is a no-op when only [v] is mapped.
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


class Locale:
    def __init__(self, code: str, language: str):
        self.code = code.lower()
        self.language = language
        self.dir = ROOT / f'assets/generated/challenger_A/{self.code}'
        self.seg_dir = self.dir / f'segments_{self.code}'
        self.dub_dir = self.dir / 'dub'
        self.lipsync_dir = self.dir / 'lipsync'
        self.caption_dir = self.dir / 'captions'
        for d in (self.seg_dir, self.dub_dir, self.lipsync_dir, self.caption_dir):
            d.mkdir(parents=True, exist_ok=True)
        upper = self.code.upper()
        self.translation_path = ROOT / f'reports/A_{upper}_translation.json'
        self.dub_manifest_path = ROOT / f'reports/A_{upper}_dub_manifest.json'
        self.build_state_path = ROOT / f'reports/A_{upper}_build_state.json'
        self.lineage_path = ROOT / f'reports/A_{upper}_lineage.json'
        self.final_path = ROOT / f'final/A_{upper}.mp4'


def stage_translate(loc: Locale) -> dict:
    if loc.translation_path.exists():
        print(f"[{loc.code}] translation cached -> {loc.translation_path}", flush=True)
        return json.loads(loc.translation_path.read_text())
    transcript = json.loads(EN_TRANSCRIPT.read_text())
    segments = transcript['segments']
    print(f"[{loc.code}] translating {len(segments)} segments -> {loc.language} (Gemini) ...", flush=True)
    translated = localize.translate_segments(segments, loc.language)
    out = {
        "source_transcript": str(EN_TRANSCRIPT),
        "provider": "gemini",
        "model": localize.GEMINI_TRANSLATE_MODEL,
        "target_language": loc.language,
        "segments": translated,
    }
    loc.translation_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"[{loc.code}] translation done -> {loc.translation_path}", flush=True)
    return out


def stage_dub(loc: Locale, translation: dict, ref_url: str) -> dict:
    manifest = json.loads(loc.dub_manifest_path.read_text()) if loc.dub_manifest_path.exists() else []
    by_id = {m['id']: m for m in manifest}
    lock = threading.Lock()

    def ensure_segment(seg):
        sid = seg['id']
        out_path = loc.dub_dir / f"seg_{sid:02d}_raw.wav"
        cached = by_id.get(sid)
        if cached and Path(cached['raw_audio']).exists():
            return None  # already cached -- no paid call
        if out_path.exists():
            dur = ffprobe_dur(out_path)
            entry = {"id": sid, "start": seg['start'], "end": seg['end'],
                      "target_duration": round(seg['end'] - seg['start'], 3),
                      "localized_text": seg['localized_text'],
                      "raw_audio": str(out_path), "raw_duration": round(dur, 3)}
            print(f"[{loc.code}][{sid}] recovered existing dub audio -> {dur:.2f}s", flush=True)
            return entry
        text = seg['localized_text']
        print(f"[{loc.code}][{sid}] synthesizing (fal TTS, {loc.language}): {text!r}", flush=True)
        audio = None
        last_err = None
        for attempt in range(3):
            try:
                audio = localize.clone_voice_tts(text, ref_url, loc.language.lower(), timeout_s=FAL_TIMEOUT)
                break
            except Exception as e:
                last_err = e
                print(f"[{loc.code}][{sid}] TTS attempt {attempt + 1} failed: {e}", flush=True)
        if audio is None:
            raise RuntimeError(f"[{loc.code}] segment {sid} TTS failed after retries: {last_err}")
        out_path.write_bytes(audio)
        dur = ffprobe_dur(out_path)
        entry = {"id": sid, "start": seg['start'], "end": seg['end'],
                  "target_duration": round(seg['end'] - seg['start'], 3),
                  "localized_text": text,
                  "raw_audio": str(out_path), "raw_duration": round(dur, 3)}
        print(f"[{loc.code}][{sid}] dub done -> {dur:.2f}s", flush=True)
        return entry

    with ThreadPoolExecutor(max_workers=TTS_WORKERS) as ex:
        futures = {ex.submit(ensure_segment, seg): seg['id'] for seg in translation['segments']}
        for fut in as_completed(futures):
            entry = fut.result()  # raises immediately on failure -- fail fast
            if entry is not None:
                with lock:
                    manifest = [m for m in manifest if m['id'] != entry['id']]
                    manifest.append(entry)
                    manifest.sort(key=lambda m: m['id'])
                    loc.dub_manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    print(f"[{loc.code}] dub stage complete -> {loc.dub_manifest_path}", flush=True)
    return {m['id']: m for m in json.loads(loc.dub_manifest_path.read_text())}


def stage_prepare_lipsync(loc: Locale, translation: dict, lipsync_ids: set, dub_by_id: dict):
    seg_by_id = {s['id']: s for s in translation['segments']}
    targets = sorted(sid for sid in lipsync_ids if sid in seg_by_id)
    if not targets:
        return

    def ensure_one(sid):
        seg = seg_by_id[sid]
        start, end = seg['start'], seg['end']
        span = end - start
        lipsynced = loc.lipsync_dir / f"seg_{sid:02d}_lipsynced.mp4"
        if lipsynced.exists():
            return sid, "cached"
        raw_video_clip = loc.lipsync_dir / f"seg_{sid:02d}_srcvideo.mp4"
        if not raw_video_clip.exists():
            run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(A_EN), "-t", f"{span:.3f}",
                 "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                 str(raw_video_clip), "-loglevel", "error"])
        aligned_wav = loc.dub_dir / f"seg_{sid:02d}_aligned.wav"
        if not aligned_wav.exists():
            align_audio(Path(dub_by_id[sid]['raw_audio']), span, aligned_wav)
        # Upload + lip-sync call are retried together: an upload can fail
        # transiently (broken pipe / connection reset) just like the fal.ai
        # job call itself, and a fresh retry needs fresh upload URLs anyway.
        out_bytes = None
        last_err = None
        for attempt in range(3):
            try:
                video_url = localize.fal_upload_file(raw_video_clip, "video/mp4")
                audio_url = localize.fal_upload_file(aligned_wav, "audio/wav")
                out_bytes = localize.lipsync_clip(video_url, audio_url, timeout_s=FAL_TIMEOUT)
                break
            except Exception as e:
                last_err = e
                print(f"[{loc.code}][{sid}] lipsync attempt {attempt + 1} failed: {e}", flush=True)
        if out_bytes is None:
            raise RuntimeError(f"[{loc.code}] segment {sid} lipsync failed after retries: {last_err}")
        lipsynced.write_bytes(out_bytes)
        return sid, "generated"

    print(f"[{loc.code}] lipsync stage: {len(targets)} segment(s) {targets}, concurrency={LIPSYNC_WORKERS}", flush=True)
    with ThreadPoolExecutor(max_workers=LIPSYNC_WORKERS) as ex:
        futures = {ex.submit(ensure_one, sid): sid for sid in targets}
        for fut in as_completed(futures):
            sid, status = fut.result()
            print(f"[{loc.code}][{sid}] lipsync {status}", flush=True)


def process_segment(loc: Locale, seg: dict, dub_by_id: dict) -> str:
    sid = seg['id']
    start, end = seg['start'], seg['end']
    span = end - start

    final_clip = loc.seg_dir / f"seg_{sid:02d}_final.mp4"
    if final_clip.exists():
        print(f"[{loc.code}][{sid}] already built, skip", flush=True)
        return str(final_clip)

    dub_entry = dub_by_id[sid]
    raw_wav = Path(dub_entry['raw_audio'])
    aligned_wav = loc.dub_dir / f"seg_{sid:02d}_aligned.wav"
    aligned_dur = ffprobe_dur(aligned_wav) if aligned_wav.exists() else align_audio(raw_wav, span, aligned_wav)

    cap_png = loc.caption_dir / f"cap_{sid:02d}.png"
    if not cap_png.exists():
        make_caption_png(dub_entry['localized_text'], cap_png)

    lipsynced = loc.lipsync_dir / f"seg_{sid:02d}_lipsynced.mp4"
    if lipsynced.exists():
        caption_over_video(lipsynced, cap_png, final_clip, with_audio=None)
        tmp_v = final_clip.with_suffix('.videoonly.mp4')
        final_clip.rename(tmp_v)
        run(["ffmpeg", "-y", "-i", str(tmp_v), "-i", str(lipsynced), "-map", "0:v", "-map", "1:a",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             "-shortest", str(final_clip), "-loglevel", "error"])
        tmp_v.unlink(missing_ok=True)
    else:
        nonlip_video = loc.seg_dir / f"seg_{sid:02d}_video.mp4"
        build_nonlipsync_video(start, span, aligned_dur, nonlip_video)
        caption_over_video(nonlip_video, cap_png, final_clip, with_audio=aligned_wav)
        nonlip_video.unlink(missing_ok=True)

    print(f"[{loc.code}][{sid}] final clip -> {ffprobe_dur(final_clip):.2f}s", flush=True)
    return str(final_clip)


def run_qa(loc: Locale) -> dict:
    p = loc.final_path
    result = {"file_exists": p.exists()}
    if not result["file_exists"]:
        result["pass"] = False
        return result

    def probe(*args):
        r = subprocess.run(["ffprobe", "-v", "error", *args, str(p)],
                            capture_output=True, text=True, timeout=30)
        return r.stdout.strip()

    vcodec = probe("-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1")
    acodec = probe("-select_streams", "a:0", "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1")
    res = probe("-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0")
    fps = probe("-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "default=nw=1:nk=1")
    dur = ffprobe_dur(p)

    decode = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "null", "-"],
                             capture_output=True, text=True, timeout=LONG_TIMEOUT)
    decode_clean = decode.returncode == 0 and not decode.stderr.strip()

    result.update({
        "resolution": res, "video_codec": vcodec, "audio_codec": acodec, "fps": fps,
        "duration_seconds": dur,
        "full_decode_clean": decode_clean,
        "full_decode_stderr": decode.stderr[-500:] if not decode_clean else "",
    })
    result["pass"] = bool(
        result["file_exists"] and vcodec == "h264" and acodec == "aac"
        and res == "1080,1920" and decode_clean
    )
    return result


def run_locale(code: str, language: str) -> dict:
    loc = Locale(code, language)
    ref_url = json.loads(REF_VOICE_URL_FILE.read_text())['reference_voice_url_fal']
    lipsync_ids = compute_lipsync_ids()
    print(f"[{loc.code}] lip-sync ids (derived from speaker-visibility classification): {sorted(lipsync_ids)}", flush=True)

    translation = stage_translate(loc)
    dub_by_id = stage_dub(loc, translation, ref_url)
    stage_prepare_lipsync(loc, translation, lipsync_ids, dub_by_id)

    state = json.loads(loc.build_state_path.read_text()) if loc.build_state_path.exists() else {"segments": {}}
    clip_paths = []
    for seg in translation['segments']:
        sid = seg['id']
        key = str(sid)
        if key in state['segments'] and Path(state['segments'][key]).exists():
            clip_paths.append(state['segments'][key])
            continue
        path = process_segment(loc, seg, dub_by_id)
        state['segments'][key] = path
        loc.build_state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        clip_paths.append(path)

    last_end = translation['segments'][-1]['end']
    tail_clip = loc.seg_dir / 'tail_cta.mp4'
    if not tail_clip.exists():
        run(["ffmpeg", "-y", "-ss", f"{last_end:.3f}", "-i", str(A_EN),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             str(tail_clip), "-loglevel", "error"], timeout=LONG_TIMEOUT)
    clip_paths.append(str(tail_clip))

    concat_list = loc.seg_dir / 'concat_list.txt'
    concat_list.write_text("\n".join(f"file '{Path(p).resolve()}'" for p in clip_paths))

    Path('final').mkdir(exist_ok=True)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "main", "-level", "4.1", "-r", "30",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
         str(loc.final_path), "-loglevel", "error"], timeout=LONG_TIMEOUT)

    print(f"[{loc.code}] render done -> {loc.final_path}, duration: {ffprobe_dur(loc.final_path):.3f}", flush=True)

    qa = run_qa(loc)
    loc.lineage_path.write_text(json.dumps({
        "output": str(loc.final_path),
        "parent": "final/A_EN.mp4",
        "target_language": loc.language,
        "translation_source": str(EN_TRANSCRIPT),
        "translation_file": str(loc.translation_path),
        "dub_manifest": str(loc.dub_manifest_path),
        "reference_voice_url_fal": ref_url,
        "lipsync_segment_ids": sorted(lipsync_ids),
        "no_retranscription": True,
        "no_a_en_a_de_rerender": True,
        "no_replicate": True,
        "tts_concurrency": TTS_WORKERS,
        "lipsync_concurrency": LIPSYNC_WORKERS,
        "qa": qa,
    }, indent=2, ensure_ascii=False))

    print(f"[{loc.code}] {'PASS' if qa.get('pass') else 'FAIL'}: {loc.final_path}", flush=True)
    return qa


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("usage: python3 scripts/localize_build.py <locale_code> <language_name>", file=sys.stderr)
        sys.exit(2)
    _, code_arg, language_arg = sys.argv
    result = run_locale(code_arg, language_arg)
    sys.exit(0 if result.get('pass') else 1)
