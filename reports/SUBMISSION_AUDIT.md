# Submission Audit — Almedia Creative Factory

Audit date: 2026-09-04. Read-only audit of the project as it currently stands. No media generated, modified, or localized as part of producing this document.

---

## 1. Final media

| Asset | Path | Duration | Resolution | Codec | Status | Purpose |
|---|---|---|---|---|---|---|
| Challenger A — English | `final/A_EN.mp4` | 57.45s | 1080x1920 | h264/aac | **Approved / frozen** | Base Challenger A build (hook_proof_timing), source for all localization |
| Challenger A — German | `final/A_DE_v2.mp4` | 57.47s | 1080x1920 | h264/aac | **Approved / frozen** (current) | ElevenLabs native-voice German localization, human-QA-approved |
| ↳ superseded | `final/A_DE.mp4` | 59.07s | 1080x1920 | h264/aac | Rejected (kept as v1 evidence) | Original Chatterbox-based German dub; later human-QA-failed (too fast / not native enough) once ElevenLabs sample was heard |
| Challenger A — French | `final/A_FR_v4.mp4` | 70.53s | 1080x1920 | h264/aac | **Approved / frozen** (current) | Natural-TTS + adaptive-timing + selective lip-sync French localization, human-QA-approved after a surgical fix (tail English leakage removed, one malformed segment rewritten) |
| ↳ superseded | `final/A_FR.mp4` | 61.07s | 1080x1920 | h264/aac | Rejected (kept as v1 evidence) | Original Chatterbox-based French dub |
| Challenger A — Korean | `final/A_KO_v4.mp4` | 68.33s | 1080x1920 | h264/aac | **Approved / frozen** (current) | Same natural-TTS architecture as French, plus a font-only caption repair (Korean glyphs were rendering as tofu boxes in v3) |
| ↳ superseded | `final/A_KO.mp4` | 64.63s | 1080x1920 | h264/aac | Rejected (kept as v1 evidence) | Original Chatterbox-based Korean dub |
| Challenger B — English v1 | `final/B_EN.mp4` | 58.34s | 1080x1920 | h264/aac | **Rejected creative iteration** (preserved as evidence) | First generative-hook attempt (face-forward reaction shot); rejected on human review, though it passed all technical QA |
| Challenger B — English v2 | `final/B_EN_v2.mp4` | 57.40s | 1080x1920 | h264/aac | **Frozen experimental candidate** — explicitly *not* claimed to outperform v1, A, or the original winner | POV bill-drop hook + real Winner 01 proof; human QA: "acceptable for experimental deployment; incremental creative value uncertain; requires performance validation" |

Note on the "3 challengers × 3 locales = 9" target in `CLAUDE.md`: only Challenger A currently has all three locales. See §6.

---

## 2. Working workflow

### What's real, committed pipeline code
- `src/config.py` — central path/constants config (single source of truth for `final/`, `manifests/`, `state/`, `reports/` layout).
- `src/manifest.py` — loads and validates challenger manifests and the source-asset inventory; raises `ManifestError` on missing files or invalid JSON, checks required keys (`experiment_id`, `parent`, `primary_variable`, `hook`, `output`).
- `src/state.py` — filesystem-based checkpoint store (`state/challenger_A.json`): per-stage status (`validate_inputs → resolve_assets → build_timeline → render → qa → lineage`), `is_completed()` / `stage_output_exists()` idempotency checks.
- `src/assets.py` — asset resolver implementing the CLAUDE.md Asset Resolution Policy in code: reuse source → re-edit/trim → caption overlay → extract B-roll → only then flag `generation_required=true`.
- `src/generate.py` — a **pluggable but intentionally unimplemented** generation interface. `request_generated_hook()` and `request_generated_segment()` both unconditionally `raise GenerationDisabled(...)`. This module was written for Challenger A (which never needed it — its hook was fully satisfiable from source) and was **not** wired up for the actual Challenger B generative work done this session (see gap below).
- `src/localize.py` — Gemini translation calls (with retry/backoff), fal.ai storage upload, fal.ai queue polling (`_fal_run`, submit → poll `status` → fetch `response`), Chatterbox TTS and sync-lipsync wrappers.
- `scripts/localize_build.py` / `scripts/build_a_de.py` — the real, resumable, checkpointed per-segment localization pipeline used for the original DE/FR/KO v1 builds: per-segment TTS → `atempo`-based duration alignment → selective fal.ai lip-sync → PIL-rendered caption overlay → per-segment compose → concat → QA.

### Actual end-to-end flow as executed
```
winner_01.mp4
  -> reports/winner_01_asset_inventory.json (source analysis)
  -> manifests/experiments/challenger_A.json (experiment definition, locked variables, primary_variable)
  -> src/assets.py-style resolution (reuse-first; deterministic ffmpeg trim/caption/freeze-hold for the hook)
  -> final/A_EN.mp4 (render) -> state/challenger_A.json (qa: PASS) -> reports/challenger_A_lineage.json
  -> per-locale translation (Gemini, reused verbatim across all locale rebuilds)
  -> per-locale voice (Chatterbox for v1 DE/FR/KO; ElevenLabs multilingual TTS for v2+ rebuilds after human QA preferred it)
  -> selective fal.ai lip-sync (sync-lipsync v2 pro) on the 5 visible-speaking segments only
  -> burned captions (PIL-rendered, locale-specific font where needed)
  -> concat/compose (ffmpeg)
  -> technical QA (ffprobe/ffmpeg decode) + full-file STT localization QA (ElevenLabs Scribe v2)
  -> human perceptual QA (approve/reject/iterate)
  -> lineage JSON per locale (reports/A_<LOCALE>_lineage.json)
```
For Challenger B, the same reuse-first philosophy applied to the body (100% real Winner 01 footage, untouched), but the **hook generation itself was executed as direct MCP fal.ai tool calls (`submit_job`/`check_job`/`get_job_result`) plus one-off Python/ffmpeg composition scripts run interactively in this session** — not through `src/generate.py`, and not committed anywhere in `scripts/`. **This is the single most important transparency point in this audit**: Claude Code (this assistant) was the interactive operator driving the fal.ai and ElevenLabs APIs turn-by-turn during this session; it was not running as an autonomous "production orchestrator" service, and a meaningful share of the v2+ localization rebuilds and all of Challenger B's generation logic exist as session-scoped scripts, not as reusable, committed pipeline code the way the original A/DE/FR/KO v1 pipeline is.

---

## 3. Reliability evidence (concrete, implemented)

| Capability | Evidence |
|---|---|
| Persistent state/checkpoints | `state/challenger_A.json` (per-stage status+timestamp); `reports/A_<LOCALE>_build_state.json` (per-segment build state); `reports/A_FR_v2_checkpoint.json` / `A_KO_v2_checkpoint.json` (dubbing-job IDs persisted immediately on creation, before polling) |
| Idempotent paid-call reuse | `scripts/localize_build.py`: every TTS/lip-sync stage checks `if <output>.exists(): return "cached"` before calling a paid API; the A_KO caption-font repair (v4) explicitly reused v3's TTS/lip-sync outputs byte-for-byte (verified via audio checksum comparison) rather than regenerating |
| Retries | `src/localize.py` Gemini call retry loop (`max_retries`); `scripts/localize_build.py` lip-sync/upload retry (`for attempt in range(3)`); Challenger B lip-sync calls retried through transient fal.ai network timeouts (both segments 7 and 20 in the Korean build hit and recovered from read/connect timeouts) |
| Concurrency | `scripts/localize_build.py`: `ThreadPoolExecutor(max_workers=TTS_WORKERS)` (4) for independent TTS jobs, `ThreadPoolExecutor(max_workers=LIPSYNC_WORKERS)` (2) for independent lip-sync jobs |
| Provider routing | Documented, human-driven routing decision recorded in `reports/A_DE_lineage.json` / `A_FR_lineage.json` / `A_KO_lineage.json`: Chatterbox (v1) → ElevenLabs multilingual TTS (v2+) after perceptual QA showed the source-voice-cloning approach produced too-fast, insufficiently native speech; ElevenLabs Dubbing v2 was evaluated and rejected for Korean specifically after it produced confirmed English/nonsense leakage |
| Technical QA | ffprobe/ffmpeg-based checks (resolution, codec, clean full decode, audio presence/levels) run on every candidate before human review; recorded in every `reports/A_*_v*.json` / `reports/A_*_elevenlabs.json` file |
| Perceptual/human QA | Explicit human approve/reject decisions recorded in every `*_lineage.json` file (`human_review_decision`, `human_review_decision_date`, `human_review_note`) — including a rejection (A_FR_v2: too fast/not native), an approval (A_FR_natural_voice_test), a partial-fail-then-fix (A_FR_v3 → v4: tail leakage + segment 6 fixed surgically), and a font-only defect report/fix cycle (A_KO_v3 → v4) |
| Targeted regeneration | A_FR_v4 regenerated only segment 6 (1 of 23) plus a tail audio mute — all 22 other segments and all 5 lip-sync outputs reused unchanged, verified via byte-identical audio comparison; A_KO_v4 regenerated captions only, verified the underlying audio track was byte-identical to v3 |
| Lineage | Every asset/version has a corresponding lineage record: `reports/challenger_A_lineage.json`, `reports/A_DE_lineage.json`, `reports/A_FR_lineage.json`, `reports/A_KO_lineage.json`, `manifests/experiments/challenger_B.json` (v1→v2) |
| Manifest validation | `src/manifest.py::load_challenger()` enforces required keys and raises on invalid JSON. **Caveat:** this validator was not actually run against `manifests/experiments/challenger_B.json` during this session — a real JSON syntax error (a stray key inside an array) was introduced by hand-editing and only caught because a later step tried to `json.load()` it manually. `src/manifest.py` exists but is not wired into every manual edit path. |

---

## 4. Experiment evidence

**Challenger A** — primary variable: `hook_proof_timing`. Hypothesis: an outcome-first opening with earlier monetary proof, while preserving the parent's persuasion architecture. `causal_claim: false` recorded in `manifests/experiments/challenger_A.json`.

**Challenger B** — primary variable: `visual_pattern_interrupt`. Hypothesis: a visually surprising but believable generative opening may increase initial attention while transitioning rapidly into genuine proof. `causal_claim: false` recorded in `manifests/experiments/challenger_B.json`.

**Neither experiment is claimed to improve performance.** No A/B-test or live-traffic data exists in this project; both manifests record hypotheses and `causal_claim: false`, not outcomes.

**B v1 → v2 as evaluation-loop evidence**: v1 (face-forward reaction shot) was generated, technically QA-passed, but **rejected on human creative review**. v2 (POV bill-drop, no identifiable face) was generated as a direct response to that rejection, inspected before composition (hand plausibility, receipt-text legibility, no logos/UI), and given a deliberately hedged verdict — "acceptable for experimental deployment; incremental creative value uncertain; requires performance validation" — rather than being declared a win. Both versions are preserved on disk (`final/B_EN.mp4`, `final/B_EN_v2.mp4`) as the audit trail.

---

## 5. Localization evidence

DE/FR/KO all followed the same eventual architecture: existing Gemini translation (reused verbatim across every version) → per-segment natural-duration TTS → adaptive video timing (loop real motion / trim, no forced compression) → fal.ai lip-sync on the same 5 visible-speaking segments (`{2,7,14,20,21}`) → burned captions → full-file STT QA.

**Voice strategy — transparency required by this audit:**
- v1 (DE/FR/KO) used `fal-ai/chatterbox/text-to-speech/multilingual` with a **cloned reference voice** from the original creator, then time-compressed (`atempo`) to fit the original English segment durations exactly.
- Human perceptual QA on that approach found it unacceptable (too fast, not sufficiently native-sounding) once an alternative was heard.
- The project **evaluated ElevenLabs Dubbing v2** (a cross-lingual, voice-preserving dubbing product) as a fix. It still forced output duration to match the source video length internally (confirmed empirically: expected-duration estimates at job submission consistently didn't match actual returned durations, which matched source length), and — separately, for Korean — produced two confirmed nonsense/English-leakage sentences embedded in otherwise-Korean audio. Dubbing v2 was rejected for production use on both grounds.
- The project then switched to **ElevenLabs standard multilingual Text-to-Speech with native target-language Voice Library voices** (not cloned from the source speaker) and no forced duration — i.e., **exact source-voice preservation was deliberately abandoned in favor of natural target-language pronunciation and cadence**, per explicit human instruction and QA approval. This is the voice strategy in every currently-frozen DE/FR/KO asset.
- **Do not read the current frozen localizations as preserving the original creator's voice identity** — they do not. They preserve meaning, monetary specificity, claims, offer, and CTA architecture exactly (each independently verified via STT on the final assembled audio), but the voice itself is a different (though natural-sounding, appropriately-cast) synthetic voice per locale.

**Final approved artifacts**: `final/A_DE_v2.mp4`, `final/A_FR_v4.mp4`, `final/A_KO_v4.mp4` (all §1 above). Superseded v1 Chatterbox-voice versions are preserved as rejected-iteration evidence, not deleted.

---

## 6. Remaining gaps — nothing below is implemented, invented, or in progress

- **Challenger C does not exist.** No manifest, no source build, no `final/C_EN.mp4`. Zero work has been done on it.
- **Challenger B has no localization.** `B_EN` / `B_EN_v2` are English-only; no `B_DE`/`B_FR`/`B_KO` exist.
- **The stated final target ("3 Challenger concepts × 3 locales = 9 final MP4 assets") is not met.** Currently complete: Challenger A × 3 locales = 3 of 9. Missing: Challenger B × 3 locales (3), Challenger C's own build plus × 3 locales (3, once C exists).
- **`src/compose.py` and `src/qa.py` are empty files (0 bytes).** The architecture diagram in `CLAUDE.md` names these as pipeline stages; in practice, composition and QA logic live in `scripts/localize_build.py`/`scripts/build_a_de.py` for the v1 pipeline, and in ad-hoc, non-committed session scripts for everything built after that (A_DE_v2 onward, all of French v2-v4, all of Korean v2-v4, all of Challenger B). Nothing routes through `src/compose.py` or `src/qa.py`.
- **`src/generate.py`'s pluggable generation interface was never actually implemented or wired up.** It still raises `GenerationDisabled` unconditionally. The real Challenger B generative-video calls in this session went directly through MCP fal.ai tools, bypassing this module entirely.
- **No automated regression/test suite.** `requirements.txt`, `run.py`, and `README.md` are all empty/placeholder files in this repo; there is no `pytest` or equivalent, and no CI.
- **No A/B performance data of any kind.** Both experiments are creative hypotheses only, explicitly marked `causal_claim: false`. There is no ad-platform integration, no traffic, no metrics pipeline — none was ever in scope (CLAUDE.md rule 9 explicitly excludes production infrastructure).
- **No UI, database, auth, or queue** — also explicitly out of scope per CLAUDE.md, not a gap relative to the stated goal, listed here only for completeness.
- **Manifest hand-edits are not consistently validated.** As noted in §3, `manifests/experiments/challenger_B.json` briefly contained invalid JSON due to a hand-edit during this session; `src/manifest.py`'s validator exists but was not run as a hook/gate on that edit.
