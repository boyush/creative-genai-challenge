# Almedia Creative Factory

A prototype creative experimentation and localization pipeline: winning
creative -> hypothesis-driven challenger -> deterministic composition ->
technical QA -> (optional) localization, with lineage recorded at every
stage. See `CLAUDE.md` for the product brief and engineering rules, and
`reports/SUBMISSION_AUDIT.md` for a dated, read-only audit of exactly what
has been built and what hasn't.

## Prototype runtime (what exists today)

```
manifest  ->  Python workflow (this repo)  ->  specialized media providers  ->  FFmpeg  ->  QA / state
```

- **manifest** -- `manifests/experiments/challenger_*.json` (per-challenger
  hypothesis/locked-variables) and `manifests/scenes/*.json` (a generic
  segment list consumed by composition: each segment is either `kind:
  "source"` — a concrete in/out trim of an existing file — or `kind:
  "generated"` — resolved through the generation cache). `src/manifest.py`
  is the mandatory validation boundary: invalid JSON or a malformed schema
  raises before any generation or render is attempted, and is never
  silently repaired.
- **Python workflow** -- `src/assets.py` (Challenger-A-style asset
  resolution per the Asset Resolution Policy), `src/generate.py`
  (cache-first selective generation: a paid provider call only happens if
  no cached asset exists AND the caller explicitly opts in), `src/compose.py`
  (segment resolution -> trim/hold/caption -> concat), `src/qa.py`
  (technical checks), `src/state.py` (filesystem checkpoints), all wired
  through `run.py` as a thin CLI.
- **specialized media providers** -- Gemini (transcription/translation),
  fal.ai (text-to-video generation, TTS, lip-sync), ElevenLabs (native
  multilingual TTS, STT QA), called directly over HTTP from
  `src/localize.py` / `src/generate.py`. No orchestration framework; every
  call is a plain `requests` call with retry/backoff and a hard timeout.
- **FFmpeg** -- all deterministic media operations (trim, freeze-hold,
  caption overlay, concat, format normalization) go through `ffmpeg`/
  `ffprobe` subprocess calls, never a video-editing library.
- **QA / state** -- `src/qa.py` runs deterministic technical checks
  (resolution, codecs, audio presence, clean decode, duration bounds)
  against an `expected` dict; `src/state.py` persists per-stage checkpoints
  to `state/*.json` so paid work is never silently redone.

### Running it

```bash
# Validate a scene manifest only (no generation/render)
python3 run.py validate manifests/scenes/challenger_B_v2.json

# Full path: validate -> resolve/generate (cache-first) -> compose -> QA -> state/lineage
python3 run.py compose manifests/scenes/challenger_B_v2.json \
  --out state/smoke/B_EN_v2_smoke.mp4 \
  --expected manifests/scenes/challenger_B_v2.expected.json \
  --challenger B_v2_smoke

# Technical QA against any existing rendered file
python3 run.py qa final/A_EN.mp4
```

`--out` exists specifically so a scene manifest's declared `output` (which
for Challenger B's manifest is the real, frozen `final/B_EN_v2.mp4`) can be
exercised against a scratch path without ever touching an approved final
asset. A live `generated` segment only calls its provider when
`--allow-paid-call` is passed *and* `generation.cache_path` has no file on
disk yet; every existing Challenger B asset already has a cached file, so
re-running against it makes zero paid calls.

### What's implemented

- `src/manifest.py` -- challenger-manifest validation (`load_challenger`)
  plus generic scene/segment-manifest validation (`load_scene_manifest`) as
  a mandatory pre-execution boundary.
- `src/assets.py` -- Challenger-A-specific timeline resolver implementing
  the Asset Resolution Policy (reuse -> re-edit -> caption -> B-roll ->
  generate).
- `src/generate.py` -- cache-first selective-generation abstraction proven
  by Challenger B's hook (fal.ai `alibaba/happy-horse/text-to-video`);
  refuses loudly (`GenerationDisabled`) rather than fabricating an asset
  when nothing is cached and no paid call was authorized.
- `src/compose.py` -- generic segment-manifest compositor (trim, freeze-
  hold, caption overlay, concat), independent of any single challenger's
  schema.
- `src/qa.py` -- deterministic technical QA (existence/size, duration,
  resolution, codecs, audio presence, clean full decode) with an
  `expected`-dict comparison mode, plus an explicit, never-automated
  `perceptual_qa_placeholder()` for human creative review.
- `src/state.py` -- filesystem checkpoint store, used by `run.py` to record
  per-stage status and by `src/generate.py`'s cache check to make paid
  calls idempotent.
- `run.py` -- CLI wiring the above into `validate` / `compose` / `qa`
  subcommands.
- `manifests/scenes/challenger_B_v2.json` -- a real scene manifest
  reproducing the actual, human-QA-approved Challenger B v2 composition
  (generated hook + real Winner 01 proof), exercised end-to-end by the
  smoke test below using only cached assets.
- The original per-locale build scripts (`scripts/build_a_de.py`,
  `scripts/localize_build.py`) that produced every frozen A/DE/FR/KO asset
  -- these remain the source of truth for the localization pipeline
  specifically (TTS/lip-sync orchestration); `src/compose.py` and
  `src/qa.py` generalize their composition/QA logic, they don't replace the
  localization-specific dub/lip-sync stages.

### What's still a gap (see `reports/SUBMISSION_AUDIT.md` §6 for detail)

- Challenger C does not exist.
- Challenger B has no localization (`B_DE`/`B_FR`/`B_KO`).
- `src/assets.py`'s resolver only understands Challenger A's manifest
  shape (`primary_variable == "hook_proof_timing"`); it is not yet
  generalized the way `src/compose.py` is. Challenger B's real composition
  is expressed as a scene manifest instead (see
  `manifests/scenes/challenger_B_v2.json`), bypassing `src/assets.py`
  entirely.
- No automated regression/test suite, no CI.
- No A/B performance data — both experiments are creative hypotheses only
  (`causal_claim: false` in every experiment manifest).

## Production evolution (not built, intentionally out of scope)

```
[n8n] / durable orchestrator  ->  workers / providers  ->  storage  ->  QA  ->  performance feedback
```

A production version of this pipeline would replace the manual/scripted
prototype runtime with:

- **Durable orchestration** (e.g. n8n, Temporal, or a queue-backed worker
  system) in place of a single Python process and hand-invoked CLI --
  retries, backoff, and resumption become the orchestrator's job, not
  ad-hoc `if cached: return` checks scattered through scripts.
- **Workers / providers** as independently scaled services (generation,
  TTS, lip-sync, transcription) behind a stable internal interface, so a
  provider can be swapped (as this project already did once, Chatterbox ->
  ElevenLabs for localization voice) without touching orchestration logic.
- **Storage** as a real asset store (object storage + a metadata DB) rather
  than a flat `assets/`/`state/`/`reports/` directory tree — this repo's
  filesystem-as-database approach is appropriate for a single-operator
  prototype, not for concurrent production use.
- **QA** as an automated gate wired into the orchestrator (technical QA
  blocking promotion automatically; perceptual/native-language QA routed to
  a human reviewer queue) instead of a CLI a person runs and reads.
- **Performance feedback** — the piece that does not exist anywhere in this
  prototype and cannot be fabricated: real ad-platform traffic and outcome
  data feeding back into which challenger/locale combinations actually get
  promoted. Every experiment in this repo is `causal_claim: false` by
  design; only live performance data could ever change that.

**Claude Code accelerated development of this prototype** — manifest
design, the fal.ai/ElevenLabs integration calls, per-locale build scripts,
and this hardening pass were all done in Claude Code sessions — **but it is
not, and is not intended to be, the production orchestrator.** The
prototype's actual runtime is `run.py` plus the `src/` modules, executable
standalone with no assistant in the loop; a production deployment would run
on the orchestrator described above, not inside a Claude Code session.
