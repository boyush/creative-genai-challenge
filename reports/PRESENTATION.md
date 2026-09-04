# Almedia Creative GenAI Specialist — Submission Presentation

6 slides, optimized for a 5–7 minute walkthrough. Speaker notes are inline
under each slide's bullets — read the bold headline, then the bullets as
talking points.

---

## Slide 1 — From Winning Creative to Learning System

**Headline:** From Winning Ads to a Repeatable Creative Learning Loop

**The problem:**
- Winning creatives contain reusable persuasion mechanics — but that knowledge usually stays informal, in someone's head, not in a system.
- Manually producing and testing iterations of a winner is slow: every challenger is a from-scratch edit.
- Global localization multiplies that cost again, per language, per challenger.

**Thesis:**
> We're not automating video generation. We're automating creative learning.

**One-line system:**
`Winner → Insight → Hypothesis → Challenger → Localization → QA → Performance`

---

## Slide 2 — Reverse-Engineering the Winners

**Cross-winner Creative Genome, in three layers:**
- **Content** — hook / proposition / claims / offer / CTA
- **Mechanics** — financial tension / curiosity / proof timing / specificity / objection handling / pattern interrupts
- **Visual DNA** — UGC framing / UI proof / dynamic captions / gameplay / camera treatment

**Recurring observed sequence:**
`relatable situation → financial tension → curiosity → specific proof → product reveal`

> **Important:** these are observed patterns across the supplied winners, not causal performance claims. Every experiment manifest in this repo records `causal_claim: false`.

**Two experiments run against that genome:**
- **Challenger A** — change proof timing (move real monetary proof earlier)
- **Challenger B** — change the visual pattern interrupt (a generative hook)

Everything else — proposition, claims, objection handling, trust proof, gameplay, payout methods, offer, CTA — stays as controlled as practical (`locked_variables` in both experiment manifests).

---

## Slide 3 — Controlled Generative Iteration

**Show:** `reports/workflow-diagrams/creative-experimentation-loop.png`

**What actually happened:**
- **Challenger A** moved authentic monetary proof earlier in the timeline — 100% reused source footage, zero generation (`hook_scene_2_source` in `manifests/experiments/challenger_A.json` reuses the real earnings-proof clip, just resequenced and caption-swapped).
- **Challenger B** generated *only* the experimental hook — a ~3.16s clip via fal.ai (`alibaba/happy-horse/text-to-video`) — then cut directly into real Winner 01 footage from the earnings-proof beat onward.
- Real payment/UI/earnings evidence remained source-controlled in both challengers — every proof segment is a `kind: "source"` trim of `input/winner_01.mp4`, never a generated one.
- **B v1** (face-forward reaction shot) passed all technical QA but **failed human creative QA** — the generated actor didn't visually match the real source creator's face in the footage that follows it.
- **B v2** (POV bill-drop hook, no identifiable face) removed that specific failure and was **frozen as a testable candidate** — not declared a winner.

> **We are not saying B v2 is better than A or the original winner.** It is a frozen, technically-passed, human-QA'd experimental candidate awaiting performance data.

**Strong line:**
> "Generative AI proposes hypotheses. Performance data determines winners."

**B generation evidence:** one selective generated segment (the hook only), cached to `assets/generated/challenger_B_v2/hook_gen_v2.mp4`, reusable without a repeat paid call, with full provider/prompt/request-id lineage recorded in `manifests/experiments/challenger_B.json`.

---

## Slide 4 — Autonomous Localization Factory

**Show:** `reports/workflow-diagrams/localization-factory.png`

**Pipeline:**
`English Challenger → timestamped transcript → translation → voice strategy → selective lip-sync → captions → render → QA → DE/FR/KO`

Challenger A is localized into all three required languages: **German, French, Korean** (`final/A_DE_v2.mp4`, `final/A_FR_v4.mp4`, `final/A_KO_v4.mp4`).

**The key prototype learning:**
> Initial localized files could pass codec/decode QA while still sounding bad.

So QA became layered, not single-gate:
`technical → language/claim QA → perceptual human gate → targeted regeneration`

**Concrete examples:**
- **A_DE v1** dubbing (Chatterbox, cloned voice) passed technical QA but sounded rushed/accented on human review — that failure is exactly what triggered the provider/voice-strategy change to ElevenLabs.
- **A_FR** malformed speech (one bad segment + tail leakage in v3) was repaired **surgically** — only that one segment and the tail were regenerated; the other 22 segments and all 5 lip-synced segments were reused byte-identical, verified by audio checksum.
- **A_KO** square-glyph ("tofu box") caption bug was repaired **at the caption-render layer only** — no paid audio or lip-sync was regenerated; the underlying audio track was verified byte-identical to the prior version.

**Transparency on voice:** exact source-voice identity was **not** preserved equally in every final locale. ElevenLabs Dubbing v2 (voice-preserving) was tested and rejected — it forced output duration to source length and, for Korean, produced confirmed English/nonsense leakage. Natural target-language delivery (ElevenLabs standard multilingual TTS, native-language voices) was prioritized instead, once perceptual QA exposed that tradeoff.

---

## Slide 5 — Working Workflow, Not a Demo Script

**Show:** `reports/workflow-diagrams/prototype-vs-production-architecture.png`

**Implemented prototype:**
`manifest → validate → resolve/cache → selective generation → compose → QA → state/lineage`

**Evidence this is a real, reusable workflow, not one-off session scripts:**
- Persistent checkpoints/state (`state/*.json`, `reports/A_*_build_state.json`)
- Paid-artifact caching (generation only calls a provider when nothing is cached)
- Retries with backoff on every provider call
- Selective concurrency (bounded thread pools for independent TTS/lip-sync jobs)
- Provider routing recorded as a decision, not hidden (Chatterbox → ElevenLabs)
- Deterministic FFmpeg composition (`src/compose.py`)
- Technical QA (`src/qa.py`)
- Human QA as an explicit, separate, non-automated gate
- Targeted regeneration (only the failed segment, never a full rebuild)
- Lineage recorded per asset/version

**Smoke-test evidence:** the existing Challenger B generated hook asset was resolved from cache and rebuilt end-to-end through the workflow —

```
python3 run.py compose manifests/scenes/challenger_B_v2.json \
  --out state/smoke/B_EN_v2_smoke.mp4 \
  --expected manifests/scenes/challenger_B_v2.expected.json \
  --challenger B_v2_smoke
```
→ **`paid_calls_made=0`**, technical QA passed (1080×1920, h264/aac, clean decode, 57.3s), and the frozen `final/B_EN_v2.mp4` was left byte-identical (md5-verified before/after).

Invalid manifests fail **before** execution — `src/manifest.py`'s validators reject malformed JSON/schema before any generation or render is attempted, verified against both a JSON-syntax break and a schema break.

> Claude Code accelerated development of this pipeline. **It is not the production runtime** — `run.py` + `src/*.py` execute standalone via plain `python3`, with no assistant process in the loop.

---

## Slide 6 — What I Would Productionize Next

**Production evolution (not implemented):**
`[n8n] / durable orchestrator → workers → media providers → storage → QA → publishing → performance feedback`

Implemented vs. future state stays explicit throughout this project — every manifest carries `causal_claim: false`, and nothing in this repo talks to an ad platform or ingests real performance data.

**Next steps:**
- Ingest real ad performance metrics
- Rank hypotheses using observed performance, not intuition
- Automate experiment allocation across challengers/locales
- Productionize provider routing and cost controls (today: manual, recorded, not automated)
- Extend localization across every approved Challenger (today: only Challenger A has all three locales)
- CI, automated tests, and schema enforcement as a build gate, not a manual validator call

> **"AI proposes creative hypotheses; deterministic automation executes them; human and performance feedback decide what survives."**

---

## Appendix — Artifact Inventory

| Artifact | Path | Status |
|---|---|---|
| Challenger A — English | `final/A_EN.mp4` | Approved / frozen |
| Challenger A — German | `final/A_DE_v2.mp4` | Approved / frozen |
| Challenger A — French | `final/A_FR_v4.mp4` | Approved / frozen |
| Challenger A — Korean | `final/A_KO_v4.mp4` | Approved / frozen |
| Challenger B — English v1 | `final/B_EN.mp4` | Rejected creative iteration (preserved as evidence) |
| Challenger B — English v2 | `final/B_EN_v2.mp4` | Frozen experimental candidate — not claimed to beat A or the winner |
| Workflow diagrams | `reports/workflow-diagrams/creative-experimentation-loop.{svg,png}`, `localization-factory.{svg,png}`, `prototype-vs-production-architecture.{svg,png}` | Rendered, verified legible |
| Experiment manifests | `manifests/experiments/challenger_A.json`, `manifests/experiments/challenger_B.json` | Hypothesis, locked variables, `causal_claim: false` |
| Scene manifest (B v2) | `manifests/scenes/challenger_B_v2.json` | Generic compose input, cache-first |
| State / checkpoints | `state/challenger_A.json`, `state/challenger_B_v2_smoke.json`, `reports/A_*_build_state.json` | Per-stage status |
| Lineage | `reports/challenger_A_lineage.json`, `reports/A_DE_lineage.json`, `reports/A_FR_lineage.json`, `reports/A_KO_lineage.json`, `reports/B_v2_smoke_scene_lineage.json` | Per-asset/version record |
| Smoke-test command | `python3 run.py compose manifests/scenes/challenger_B_v2.json --out state/smoke/B_EN_v2_smoke.mp4 --expected manifests/scenes/challenger_B_v2.expected.json --challenger B_v2_smoke` | — |
| Smoke-test result | `paid_calls_made=0`; technical QA pass; `final/B_EN_v2.mp4` unchanged (md5-verified) | Output: `state/smoke/B_EN_v2_smoke.mp4` |

---

## 90-Second Demo Sequence

Open these in order; total budget ~90s. Times are cumulative.

1. **0:00–0:15 — `final/A_EN.mp4`** (play first ~5s). Point out: the winning persuasion architecture, now with the outcome-first hook and earlier real monetary proof (Challenger A's `hook_proof_timing` experiment).
2. **0:15–0:30 — `final/B_EN.mp4`** (play first ~5s, generated hook only). Point out: technically clean, but this is the *rejected* version — the generated protagonist doesn't match the real creator in the footage that follows. Say out loud: "this failed human QA, on purpose shown first."
3. **0:30–0:50 — `final/B_EN_v2.mp4`** (play first ~6s through the cut into real footage). Point out: POV hook removes the face-mismatch problem entirely, then cuts straight into the same real Winner 01 proof — frozen as a candidate, not declared a winner.
4. **0:50–1:05 — `final/A_FR_v4.mp4`** or **`final/A_DE_v2.mp4`** (play ~5s with captions visible). Point out: natural target-language voice, retimed burned-in captions, selective lip-sync only where the speaker is visibly talking.
5. **1:05–1:20 — `reports/workflow-diagrams/creative-experimentation-loop.png`**, then **`localization-factory.png`**. Point out: the decision diamond (reuse vs. generate-only-the-variable) and the layered QA chain (technical → language → human → targeted regeneration).
6. **1:20–1:30 — terminal: re-run the smoke-test command** (or open `reports/B_v2_smoke_scene_lineage.json`). Point out the line `"paid_calls_made": 0` — proof the cached generated asset resolves without spending again, and that `final/B_EN_v2.mp4` was never touched by the run.
