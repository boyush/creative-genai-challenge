"""
A_EN -> A_DE localization pipeline (vertical slice).

Providers (explicitly approved, see reports/challenger_A_de_lineage.json):
  - transcription : Gemini (GEMINI_API_KEY) -- OpenAI Whisper blocked (quota exhausted)
  - translation    : Gemini (GEMINI_API_KEY) -- OpenAI GPT blocked (quota exhausted)
  - voice dub      : Replicate resemble-ai/chatterbox-multilingual (REPLICATE_API_TOKEN)
  - lip-sync       : Replicate sync/lipsync-2 (REPLICATE_API_TOKEN)

This module intentionally does not call OpenAI. Do not silently add/switch
providers here without the same explicit-approval flow used for this
milestone.
"""
import base64
import json
import os
import time
import subprocess
from pathlib import Path

import requests


def _load_dotenv(path: Path = Path(__file__).resolve().parent.parent / ".env") -> None:
    """Load KEY=VALUE lines from .env into os.environ, overriding any stale
    process-level value (the shell's persisted env may hold an older key)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ[key.strip()] = value.strip()


_load_dotenv()

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
FAL_KEY = os.environ["FAL_KEY"]

GEMINI_TRANSCRIBE_MODEL = "gemini-3.6-flash"
GEMINI_TRANSLATE_MODEL = "gemini-3.6-flash"

FAL_TTS_MODEL = "fal-ai/chatterbox/text-to-speech/multilingual"
FAL_LIPSYNC_MODEL = "fal-ai/sync-lipsync/v2/pro"

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
REPLICATE_BASE = "https://api.replicate.com/v1"


def _gemini_generate(model: str, parts: list, response_schema: dict | None = None,
                      temperature: float = 0.1, max_retries: int = 3) -> dict:
    url = f"{GEMINI_BASE}/models/{model}:generateContent?key={GEMINI_API_KEY}"
    gen_config = {"temperature": temperature}
    if response_schema:
        gen_config["responseMimeType"] = "application/json"
        gen_config["responseSchema"] = response_schema
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": gen_config,
    }
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=180)
        except requests.RequestException as e:
            last_err = f"network error: {e}"
            time.sleep(2 * attempt)
            continue
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 500, 502, 503, 504):
            last_err = f"HTTP {resp.status_code}: {resp.text[:500]}"
            time.sleep(3 * attempt)
            continue
        raise RuntimeError(f"Gemini call failed (non-retryable) HTTP {resp.status_code}: {resp.text[:1000]}")
    raise RuntimeError(f"Gemini call failed after {max_retries} retries: {last_err}")


def transcribe_audio_gemini(audio_path: Path) -> dict:
    """Timestamped transcription via Gemini audio understanding.

    Gemini does not provide forced-alignment word timestamps the way
    Whisper does, so this requests SEGMENT-level timestamps only (natural
    speech/pause boundaries) and marks word-level timestamps as
    unavailable. This limitation is recorded in the returned dict and
    must be carried into lineage.
    """
    audio_bytes = audio_path.read_bytes()
    b64 = base64.b64encode(audio_bytes).decode("ascii")

    schema = {
        "type": "object",
        "properties": {
            "detected_language": {"type": "string"},
            "duration_seconds_estimate": {"type": "number"},
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "start": {"type": "number"},
                        "end": {"type": "number"},
                        "text": {"type": "string"},
                    },
                    "required": ["id", "start", "end", "text"],
                },
            },
        },
        "required": ["detected_language", "segments"],
    }

    prompt = (
        "You are a precise audio transcription tool. Transcribe the spoken "
        "English in this audio file completely and accurately. "
        "Segment the transcript at natural speech boundaries (pauses, "
        "sentence/clause breaks) -- do not merge the whole thing into one "
        "segment, aim for phrase-sized segments of roughly 1-4 seconds each. "
        "For every segment give the start and end time in seconds from the "
        "start of the audio, as accurately as you can perceive it. "
        "Cover the ENTIRE audio duration with contiguous, non-overlapping "
        "segments (no gaps except genuine silence). "
        "Return only the structured JSON described by the schema. "
        "Do not translate. Do not paraphrase. Transcribe verbatim what is spoken."
    )

    parts = [
        {"text": prompt},
        {"inline_data": {"mime_type": "audio/wav", "data": b64}},
    ]
    raw = _gemini_generate(GEMINI_TRANSCRIBE_MODEL, parts, response_schema=schema, temperature=0.0)
    text_out = raw["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(text_out)

    return {
        "provider": "gemini",
        "model": GEMINI_TRANSCRIBE_MODEL,
        "timestamp_granularity": "segment",
        "word_timestamps_available": False,
        "word_timestamps_note": (
            "OpenAI Whisper (native word-level forced alignment) was blocked "
            "by exhausted API quota. Gemini audio understanding was used "
            "instead (explicitly approved substitute); it does not provide "
            "forced-alignment word timestamps, so only segment-level "
            "timestamps are recorded as verified. Caption timing is derived "
            "deterministically within these validated segments, not from "
            "invented word timings."
        ),
        "detected_language": parsed.get("detected_language"),
        "segments": parsed["segments"],
    }


def translate_segments(segments: list[dict], target_language: str, product_name: str = "Freecash") -> list[dict]:
    """Generalized locale-agnostic version of translate_segments_gemini.

    Same rules (preserve product name/amounts/claims exactly, don't
    strengthen claims, natural spoken register, roughly length-matched to
    source span, one output per input id) for an arbitrary target_language.
    Adds a 'localized_text' key to each returned segment (does not mutate
    or reuse the DE-specific 'de_text' key)."""
    schema = {
        "type": "object",
        "properties": {
            "translations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "text": {"type": "string"},
                    },
                    "required": ["id", "text"],
                },
            }
        },
        "required": ["translations"],
    }

    src_payload = [{"id": s["id"], "start": s["start"], "end": s["end"], "text": s["text"]} for s in segments]

    prompt = (
        f"Translate the following English UGC-ad voiceover segments into natural, "
        f"spoken, colloquial {target_language} suitable for a TikTok-native ad read "
        "aloud by a young adult creator. Rules:\n"
        f"- Keep the product name '{product_name}' unchanged in every segment "
        "that mentions it (do not translate or decline it).\n"
        "- Preserve all monetary amounts and factual claims exactly in meaning "
        "(same numbers, same currency sense) -- do not invent, drop, or "
        "exaggerate any claim or amount.\n"
        "- Do NOT strengthen or embellish advertising claims beyond the source.\n"
        f"- Prefer natural spoken {target_language} phrasing over literal word-for-word "
        "translation, but stay faithful to meaning.\n"
        "- Keep each translated segment roughly matched in spoken length to "
        "its source segment's duration (col 'end'-'start' seconds) so it can "
        "be dubbed into the same time slot -- prefer concise phrasing over "
        "padding.\n"
        "- Translate every segment id given; do not merge or split segments; "
        "return exactly one translation per input id, in the same order.\n\n"
        f"Segments (JSON): {json.dumps(src_payload, ensure_ascii=False)}"
    )

    raw = _gemini_generate(GEMINI_TRANSLATE_MODEL, [{"text": prompt}], response_schema=schema, temperature=0.2)
    text_out = raw["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(text_out)
    by_id = {t["id"]: t["text"] for t in parsed["translations"]}

    out = []
    for s in segments:
        out.append({**s, "localized_text": by_id.get(s["id"], "")})
    return out


def translate_segments_gemini(segments: list[dict], product_name: str = "Freecash") -> list[dict]:
    """Translate transcript segments into natural spoken German ad copy.

    Preserves: product name, monetary amounts/factual claims (meaning),
    does not strengthen claims, one JSON object per input segment id.
    """
    schema = {
        "type": "object",
        "properties": {
            "translations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "de_text": {"type": "string"},
                    },
                    "required": ["id", "de_text"],
                },
            }
        },
        "required": ["translations"],
    }

    src_payload = [{"id": s["id"], "start": s["start"], "end": s["end"], "text": s["text"]} for s in segments]

    prompt = (
        "Translate the following English UGC-ad voiceover segments into natural, "
        "spoken, colloquial German suitable for a TikTok-native ad read aloud by "
        "a young adult creator. Rules:\n"
        f"- Keep the product name '{product_name}' unchanged in every segment "
        "that mentions it (do not translate or decline it).\n"
        "- Preserve all monetary amounts and factual claims exactly in meaning "
        "(same numbers, same currency sense) -- do not invent, drop, or "
        "exaggerate any claim or amount.\n"
        "- Do NOT strengthen or embellish advertising claims beyond the source.\n"
        "- Prefer natural spoken German phrasing over literal word-for-word "
        "translation, but stay faithful to meaning.\n"
        "- Keep each translated segment roughly matched in spoken length to "
        "its source segment's duration (col 'end'-'start' seconds) so it can "
        "be dubbed into the same time slot -- prefer concise phrasing over "
        "padding.\n"
        "- Translate every segment id given; do not merge or split segments; "
        "return exactly one translation per input id, in the same order.\n\n"
        f"Segments (JSON): {json.dumps(src_payload, ensure_ascii=False)}"
    )

    raw = _gemini_generate(GEMINI_TRANSLATE_MODEL, [{"text": prompt}], response_schema=schema, temperature=0.2)
    text_out = raw["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(text_out)
    by_id = {t["id"]: t["de_text"] for t in parsed["translations"]}

    out = []
    for s in segments:
        out.append({**s, "de_text": by_id.get(s["id"], "")})
    return out


# ---------------- fal.ai helpers ----------------

FAL_QUEUE_BASE = "https://queue.fal.run"
FAL_REST_BASE = "https://rest.alpha.fal.ai"


def fal_upload_file(local_path: Path, content_type: str) -> str:
    """Two-step fal.ai storage upload (initiate -> PUT bytes). Returns the
    public file_url. Used instead of routing raw bytes through any other
    channel, matching fal's documented upload flow."""
    headers = {"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"}
    init = requests.post(
        f"{FAL_REST_BASE}/storage/upload/initiate",
        headers=headers,
        json={"file_name": local_path.name, "content_type": content_type},
        timeout=30,
    )
    init.raise_for_status()
    info = init.json()
    put_resp = requests.put(
        info["upload_url"],
        headers={"Content-Type": content_type},
        data=local_path.read_bytes(),
        timeout=120,
    )
    put_resp.raise_for_status()
    return info["file_url"]


def _fal_run(model: str, input_payload: dict, poll_interval: float = 3.0,
             timeout_s: float = 600.0) -> dict:
    headers = {"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"}
    create_resp = requests.post(
        f"{FAL_QUEUE_BASE}/{model}",
        headers=headers,
        json=input_payload,
        timeout=60,
    )
    if create_resp.status_code != 200:
        raise RuntimeError(f"fal.ai submit failed for {model}: HTTP {create_resp.status_code}: {create_resp.text[:800]}")
    job = create_resp.json()
    status_url = job["status_url"]
    response_url = job["response_url"]
    start = time.time()
    while True:
        if time.time() - start > timeout_s:
            raise RuntimeError(f"fal.ai job {job.get('request_id')} ({model}) timed out after {timeout_s}s")
        st = requests.get(status_url, headers=headers, timeout=30)
        st.raise_for_status()
        status = st.json().get("status")
        if status == "COMPLETED":
            res = requests.get(response_url, headers=headers, timeout=60)
            if res.status_code != 200:
                raise RuntimeError(f"fal.ai job {job.get('request_id')} ({model}) result fetch failed: HTTP {res.status_code}: {res.text[:800]}")
            return res.json()
        if status in ("ERROR", "FAILED"):
            raise RuntimeError(f"fal.ai job {job.get('request_id')} ({model}) {status}: {st.text[:800]}")
        time.sleep(poll_interval)


def clone_voice_tts_de(text: str, reference_audio_url: str) -> bytes:
    """fal-ai/chatterbox/text-to-speech/multilingual: text -> German speech
    in the reference speaker's voice. Returns raw audio bytes (wav)."""
    result = _fal_run(
        FAL_TTS_MODEL,
        {
            "text": text,
            "voice": reference_audio_url,
            "custom_audio_language": "german",
            "cfg_scale": 0.5,
            "temperature": 0.7,
            "exaggeration": 0.5,
        },
    )
    audio_url = result["audio"]["url"]
    r = requests.get(audio_url, timeout=120)
    r.raise_for_status()
    return r.content


def clone_voice_tts(text: str, reference_audio_url: str, custom_audio_language: str,
                     timeout_s: float = 600.0) -> bytes:
    """Generalized locale-agnostic version of clone_voice_tts_de: text ->
    speech in `custom_audio_language`, in the reference speaker's voice.
    Same model/params as the proven DE path; only the language and
    timeout are parametrized. Returns raw audio bytes (wav)."""
    result = _fal_run(
        FAL_TTS_MODEL,
        {
            "text": text,
            "voice": reference_audio_url,
            "custom_audio_language": custom_audio_language,
            "cfg_scale": 0.5,
            "temperature": 0.7,
            "exaggeration": 0.5,
        },
        timeout_s=timeout_s,
    )
    audio_url = result["audio"]["url"]
    r = requests.get(audio_url, timeout=120)
    r.raise_for_status()
    return r.content


def lipsync_clip(video_url: str, audio_url: str, sync_mode: str = "loop",
                  timeout_s: float = 900.0) -> bytes:
    result = _fal_run(
        FAL_LIPSYNC_MODEL,
        {
            "video_url": video_url,
            "audio_url": audio_url,
            "sync_mode": sync_mode,
        },
        timeout_s=timeout_s,
    )
    out_url = result["video"]["url"]
    r = requests.get(out_url, timeout=180)
    r.raise_for_status()
    return r.content


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())
