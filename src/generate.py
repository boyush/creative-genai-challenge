"""
Selective-generation abstraction: the pattern actually proven for
Challenger B (v1 and v2) --

  experiment manifest -> generated segment request -> persisted provider
  metadata -> cached asset -> composition

-- represented as reusable code instead of one-off MCP tool calls run
interactively in a session. Preserves the CLAUDE.md principle behind
Challenger B: generate ONLY the experimental segment (the hook); every
piece of real UI/payment/earnings proof must come from a "source" segment
in the scene manifest (src/manifest.py::load_scene_manifest), never from
here.

Cache-first is the default and only path this milestone exercises: if
generation.cache_path already exists on disk, that asset is returned with
zero network calls and zero spend -- this is what makes re-running against
the existing Challenger B assets idempotent (no repeat paid generation).
A live call only happens when the caller explicitly passes
allow_paid_call=True AND no cached asset exists; that is a genuine
blocker/opt-in, not a silent fallback (CLAUDE.md rule #8: external
generation must have a deterministic fallback -- here that fallback is
"stop and report the blocker", not "fabricate a substitute").

Provider support: fal.ai (the queue submit/poll/fetch pattern already
proven in src/localize.py::_fal_run), reused rather than reimplemented.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class GenerationDisabled(RuntimeError):
    """Raised when a segment has no cached asset and no explicit
    allow_paid_call=True was given. Fails loudly rather than fabricating
    or silently substituting a stand-in asset (CLAUDE.md rules #4, #8)."""


class GenerationError(RuntimeError):
    """Raised when an explicitly-requested live provider call fails."""


@dataclass
class GeneratedAsset:
    path: Path
    source: str  # "cache" | "provider"
    provider: Optional[str] = None
    endpoint_id: Optional[str] = None
    request_id: Optional[str] = None


def request_generated_segment(segment_spec: dict, *, allow_paid_call: bool = False) -> GeneratedAsset:
    """segment_spec must carry a 'generation' block (or be one itself) with:
      cache_path   -- local path checked BEFORE any paid call
      provider     -- currently only "fal.ai" is implemented
      endpoint_id  -- fal.ai model id (e.g. "alibaba/happy-horse/text-to-video")
      prompt       -- text prompt
      input_params -- dict of extra provider params (duration, resolution, ...)
    """
    gen = segment_spec.get("generation", segment_spec)
    if "cache_path" not in gen:
        raise GenerationError(f"segment {segment_spec.get('id')!r}: generation spec has no cache_path")
    cache_path = Path(gen["cache_path"])

    if cache_path.exists() and cache_path.stat().st_size > 0:
        return GeneratedAsset(
            path=cache_path, source="cache",
            provider=gen.get("provider"), endpoint_id=gen.get("endpoint_id"),
            request_id=gen.get("request_id"),
        )

    if not allow_paid_call:
        raise GenerationDisabled(
            f"segment {segment_spec.get('id')!r} has no cached asset at "
            f"{cache_path} and allow_paid_call=False. Genuine blocker: the "
            f"default/verification path never spends -- either supply the "
            f"cached asset or explicitly pass allow_paid_call=True to spend."
        )

    provider = gen.get("provider")
    if provider != "fal.ai":
        raise GenerationError(f"unsupported provider: {provider!r} (only 'fal.ai' is implemented)")

    from src import localize  # deferred import: touches .env/requests only on an actual live call
    if not localize.FAL_KEY:
        raise GenerationError("FAL_KEY not set; cannot make a live fal.ai call")
    if "endpoint_id" not in gen or "prompt" not in gen:
        raise GenerationError(f"segment {segment_spec.get('id')!r}: generation spec needs endpoint_id + prompt for a live call")

    import requests

    result = localize._fal_run(
        gen["endpoint_id"],
        {"prompt": gen["prompt"], **gen.get("input_params", {})},
        timeout_s=gen.get("timeout_s", 300.0),
    )
    video_url = result.get("video", {}).get("url")
    if not video_url:
        raise GenerationError(f"fal.ai response for {gen['endpoint_id']} had no video.url: {result}")
    r = requests.get(video_url, timeout=180)
    r.raise_for_status()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(r.content)

    return GeneratedAsset(
        path=cache_path, source="provider", provider="fal.ai",
        endpoint_id=gen["endpoint_id"], request_id=result.get("request_id"),
    )


def request_generated_hook(challenger: dict) -> GeneratedAsset:
    """Back-compat entrypoint for src/assets.py's Challenger-A-style
    resolver, which calls this when a manifest declares its hook cannot be
    built from existing footage. Reads a 'hook_generation' block off the
    challenger manifest (same shape as a scene-manifest segment's
    'generation' block) rather than guessing a cache path. Not exercised by
    Challenger A (its hook is fully source-built); provided for any future
    challenger whose manifest declares one."""
    gen = challenger.get("hook_generation")
    if not gen:
        raise GenerationDisabled(
            f"{challenger.get('experiment_id')} requires a generated hook "
            f"but the manifest declares no 'hook_generation' block with a "
            f"cache_path. Genuine blocker: add one before rerunning."
        )
    return request_generated_segment({"id": "hook", "generation": gen}, allow_paid_call=False)
