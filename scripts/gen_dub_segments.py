import sys, json, time
sys.path.insert(0, '.')
from pathlib import Path
from src import localize

translation = json.loads(Path('reports/A_DE_translation.json').read_text())
ref_url = json.loads(Path('assets/generated/challenger_A/de/reference_voice_url_fal.json').read_text())['reference_voice_url_fal']

out_dir = Path('assets/generated/challenger_A/de/dub')
out_dir.mkdir(parents=True, exist_ok=True)

manifest_path = Path('reports/A_DE_dub_manifest.json')
manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
done_ids = {m['id'] for m in manifest}

for seg in translation['segments']:
    sid = seg['id']
    out_path = out_dir / f"seg_{sid:02d}_raw.wav"
    if sid not in done_ids and out_path.exists():
        # audio was generated in a prior (interrupted) run but not recorded
        dur = localize.ffprobe_duration(out_path)
        manifest.append({"id": sid, "start": seg['start'], "end": seg['end'], "target_duration": round(seg['end']-seg['start'],3),
                          "de_text": seg['de_text'], "raw_audio": str(out_path), "raw_duration": round(dur,3)})
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        done_ids.add(sid)
        print(f"[{sid}] recovered existing audio -> {dur:.2f}s (target {seg['end']-seg['start']:.2f}s)", flush=True)
    if sid in done_ids:
        continue
    text = seg['de_text']
    out_path = out_dir / f"seg_{sid:02d}_raw.wav"
    print(f"[{sid}] synthesizing: {text!r}", flush=True)
    for attempt in range(3):
        try:
            audio = localize.clone_voice_tts_de(text, ref_url)
            out_path.write_bytes(audio)
            break
        except Exception as e:
            print(f"  attempt {attempt+1} failed: {e}", flush=True)
            time.sleep(3)
    else:
        raise RuntimeError(f"segment {sid} TTS failed after retries")
    dur = localize.ffprobe_duration(out_path)
    manifest.append({"id": sid, "start": seg['start'], "end": seg['end'], "target_duration": round(seg['end']-seg['start'],3),
                      "de_text": text, "raw_audio": str(out_path), "raw_duration": round(dur,3)})
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"  -> {dur:.2f}s (target {seg['end']-seg['start']:.2f}s)", flush=True)

print("DONE, wrote reports/A_DE_dub_manifest.json")
