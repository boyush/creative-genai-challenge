# Almedia Creative Factory — Workflow Sketch

Three diagrams for transfer into Miro/slides: the creative-experimentation
loop, the localization factory, and prototype-vs-production architecture.
Every node is labeled against what this repo actually contains today
(`src/*.py`, `run.py`, `manifests/`, `state/`, `reports/`) — nothing here
claims capability that doesn't exist. Future/production-only stages are
drawn dashed and labeled FUTURE.

Legend used in all three diagrams:

| Style | Meaning |
|---|---|
| 🟩 solid green | IMPLEMENTED — real code/data in this repo |
| 🟨 solid amber | HUMAN GATE — a human decision point, not automated |
| 🟦 solid blue | EXTERNAL AI/MEDIA — a paid third-party provider call |
| ⬜ dashed grey | FUTURE / PRODUCTION — not implemented |

---

## Diagram 1 — Creative Experimentation Loop

```mermaid
flowchart TD
  classDef implemented fill:#d4edda,stroke:#28a745,color:#14532d;
  classDef humangate fill:#fff3cd,stroke:#d39e00,color:#664d03;
  classDef external fill:#cfe2ff,stroke:#0d6efd,color:#052c65;
  classDef future fill:#eeeeee,stroke:#888888,stroke-dasharray: 4 3,color:#555555;

  subgraph LEGEND["Legend"]
    direction LR
    L1["IMPLEMENTED"]:::implemented
    L2["HUMAN GATE"]:::humangate
    L3["EXTERNAL AI/MEDIA"]:::external
    L4["FUTURE / PRODUCTION"]:::future
  end

  WC["Winning Creative<br/>input/winner_01.mp4"]:::implemented
  CG["Winner Analysis / Creative Genome<br/>reports/winner_01_asset_inventory.json"]:::implemented
  EH["Experiment Hypothesis<br/>causal_claim: false"]:::implemented
  EM["Experiment Manifest + Validation<br/>manifests/experiments/*.json<br/>src/manifest.py::load_challenger"]:::implemented
  DEC{"Reuse existing asset OR<br/>generate ONLY the changed<br/>creative variable?"}:::implemented
  NOTE1["Real payment / earnings / UI proof is<br/>ALWAYS a source-controlled 'kind: source' trim —<br/>never generated"]:::humangate
  AR["Asset Resolution / Cache<br/>src/assets.py (Asset Resolution Policy)<br/>src/generate.py (cache-first)"]:::implemented
  GEN["Selective Generation<br/>fal.ai — hook segment ONLY,<br/>~3-5s, never the whole ad"]:::external
  NOTE2["Generative media touches only the<br/>experimental segment (the hook) —<br/>body/proof is always reused real footage"]:::humangate
  SM["Scene Manifest<br/>manifests/scenes/*.json"]:::implemented
  DC["Deterministic Composition<br/>src/compose.py + FFmpeg"]:::implemented
  TQA["Technical QA<br/>src/qa.py"]:::implemented
  HQA["Human Creative QA"]:::humangate
  CHAL["Challenger Asset<br/>A = hook / proof timing<br/>B = visual pattern interrupt"]:::implemented
  ABT["A/B Performance Test"]:::future
  PI["Performance Ingestion /<br/>Automatic Learning"]:::future

  WC --> CG --> EH --> EM --> DEC
  DEC -->|"reuse"| AR
  DEC -->|"generate changed variable only"| GEN --> AR
  DEC -.- NOTE1
  GEN -.- NOTE2
  AR --> SM --> DC --> TQA --> HQA --> CHAL --> ABT
  ABT -.->|"FUTURE STATE — no ad-platform<br/>integration exists in this repo"| PI
  PI -.->|"dashed feedback, not implemented"| CG
```

**Evidence from the actual prototype:**
- Challenger A (`hook_proof_timing`) was built **100% from source reuse** — `reports/winner_01_asset_inventory.json` found the hook fully satisfiable from existing footage, so `src/generate.py` was never invoked; Challenger B (`visual_pattern_interrupt`) generated **only a ~3.16s hook** via fal.ai (`alibaba/happy-horse/text-to-video`) and cut directly into real `winner_01.mp4` footage from the earnings-proof beat onward (`manifests/scenes/challenger_B_v2.json`).
- Every real payment/earnings/UI proof segment in both challengers is a `kind: "source"` trim of `input/winner_01.mp4` — never a generated segment.
- `src/generate.py::request_generated_segment()` raises `GenerationDisabled` rather than fabricating an asset when nothing is cached and no paid call is authorized — verified live against a synthetic no-cache manifest (clean exit 3, no output file created).
- `src/manifest.py`'s validators reject invalid JSON and malformed schema **before** any generation or render runs — verified against both a JSON-syntax break and a schema break (this is the exact failure class that broke Challenger B's manifest by hand-edit during the original build).
- No A/B performance-test integration exists anywhere in this repo; every experiment manifest records `causal_claim: false` — the "A/B Performance Test" and "Performance Ingestion" stages are drawn as FUTURE STATE, not implemented.

---

## Diagram 2 — Localization Factory

```mermaid
flowchart TD
  classDef implemented fill:#d4edda,stroke:#28a745,color:#14532d;
  classDef humangate fill:#fff3cd,stroke:#d39e00,color:#664d03;
  classDef external fill:#cfe2ff,stroke:#0d6efd,color:#052c65;
  classDef future fill:#eeeeee,stroke:#888888,stroke-dasharray: 4 3,color:#555555;

  subgraph LEGEND["Legend"]
    direction LR
    L1["IMPLEMENTED"]:::implemented
    L2["HUMAN GATE"]:::humangate
    L3["EXTERNAL AI/MEDIA"]:::external
    L4["FUTURE / PRODUCTION"]:::future
  end

  AEN["Approved English Challenger<br/>final/A_EN.mp4"]:::implemented
  TR["Timestamped Transcript<br/>Gemini, segment-level"]:::external
  TX["Translation DE / FR / KO<br/>Gemini, claims/amounts preserved exactly"]:::external
  VR["Voice Strategy / Provider Routing<br/>Chatterbox cloned-voice → REJECTED (too fast)<br/>ElevenLabs Dubbing v2 → REJECTED (forced duration, KO leakage)<br/>ElevenLabs multilingual TTS, native voice → SELECTED"]:::implemented
  NA["Natural Target-Language Audio<br/>ElevenLabs multilingual TTS"]:::external
  LS["Selective Lip-sync / Reface<br/>fal.ai sync-lipsync v2 pro —<br/>ONLY segments where speaker visibly talks"]:::external
  CAP["Retimed Burned-in Captions<br/>PIL-rendered PNG overlay"]:::implemented
  COMP["Composition<br/>src/compose.py + FFmpeg"]:::implemented
  TQA2["Technical QA<br/>src/qa.py — codec / res / decode / duration"]:::implemented
  LQA["Language / Claim QA<br/>full-file STT verification"]:::external
  NOTE3["Technical PASS does NOT imply<br/>perceptual PASS — proven by A_DE v1"]:::humangate
  HQA2["Human Perceptual QA<br/>native-speaker review"]:::humangate
  DEC2{"Passed human QA?"}:::humangate
  TRG["Targeted Regeneration<br/>only the failed segment(s)"]:::implemented
  APP["Approved Localized Asset<br/>final/A_DE_v2, A_FR_v4, A_KO_v4"]:::implemented

  subgraph SIDE["Persistent Sidecars"]
    direction LR
    ST["State / Checkpoints<br/>reports/A_*_build_state.json"]:::implemented
    CA["Cache<br/>skip any stage whose output already exists"]:::implemented
    RE["Retries<br/>bounded retry + backoff per provider call"]:::implemented
    LI["Lineage<br/>reports/A_*_lineage.json"]:::implemented
  end

  AEN --> TR --> TX --> VR --> NA --> LS --> CAP --> COMP --> TQA2 --> LQA --> HQA2 --> DEC2
  TQA2 -.- NOTE3
  DEC2 -->|"pass"| APP
  DEC2 -->|"fail"| TRG --> COMP

  SIDE -.->|"backs"| TX
  SIDE -.->|"backs"| NA
  SIDE -.->|"backs"| LS
  SIDE -.->|"backs"| COMP
  SIDE -.->|"backs"| TRG
```

**Evidence from the actual prototype:**
- **A_DE v1** (Chatterbox cloned-voice TTS) **passed technical QA but was rejected by human perceptual QA** — "too fast, not sufficiently native-sounding" once the ElevenLabs alternative was heard. This is the project's clearest technical-PASS-vs-perceptual-fail case, and the reason `NOTE3` sits directly on the technical-QA→language-QA edge.
- Voice strategy was **evaluated, not assumed**: ElevenLabs Dubbing v2 (voice-preserving) was tested and rejected for forcing output duration to source length and, for Korean specifically, for producing confirmed English/nonsense leakage; the project moved to ElevenLabs standard multilingual TTS with native target-language voices, **deliberately abandoning source-voice-identity preservation** per human QA — not every final locale preserves the original creator's voice.
- **A_FR targeted repair**: v1 (Chatterbox) → v2 (rejected: too fast) → natural-voice test (approved) → v3 (partial fail: tail English-audio leakage + one malformed segment) → **v4 regenerated only segment 6 and the tail — the other 22 segments and all 5 lip-sync outputs were reused byte-identical**, verified via audio checksum.
- **A_KO targeted repair**: v3 → v4 was a **caption-only fix** (Korean glyphs rendering as tofu boxes in v3); the underlying audio track was verified byte-identical to v3 — no TTS or lip-sync was regenerated.
- Lip-sync was applied **selectively**, only to the segments where the speaker is visibly talking on-screen (derived from `reports/A_EN_speaker_visual_analysis.json`), not to the whole video — the same 5 segment IDs across DE/FR/KO.

---

## Diagram 3 — Prototype vs Production Architecture

```mermaid
flowchart LR
  classDef implemented fill:#d4edda,stroke:#28a745,color:#14532d;
  classDef humangate fill:#fff3cd,stroke:#d39e00,color:#664d03;
  classDef external fill:#cfe2ff,stroke:#0d6efd,color:#052c65;
  classDef future fill:#eeeeee,stroke:#888888,stroke-dasharray: 4 3,color:#555555;
  classDef devenv fill:#f5e6ff,stroke:#8a2be2,color:#3d1361,stroke-dasharray: 2 2;

  subgraph LEGEND["Legend"]
    direction LR
    L1["IMPLEMENTED"]:::implemented
    L2["HUMAN GATE"]:::humangate
    L3["EXTERNAL AI/MEDIA"]:::external
    L4["FUTURE / PRODUCTION"]:::future
  end

  CC["Claude Code<br/>development environment<br/>(NOT part of runtime execution)"]:::devenv

  subgraph PROTO["IMPLEMENTED PROTOTYPE"]
    direction TB
    CLI["CLI / Manifest<br/>run.py validate / compose / qa"]:::implemented
    PCF["Python Creative Factory<br/>src/*.py"]:::implemented
    AIP["Specialized AI/Media Providers<br/>Gemini · fal.ai · ElevenLabs"]:::external
    FF["FFmpeg / ffprobe"]:::implemented
    QAP["QA<br/>src/qa.py"]:::implemented
    FS["Filesystem State / Cache / Lineage<br/>state/*.json, reports/*.json"]:::implemented
    CLI --> PCF --> AIP --> FF --> QAP --> FS
  end

  CC -.->|"accelerated building/hardening this,<br/>runs standalone via plain python3"| CLI

  subgraph PROD["PRODUCTION EVOLUTION — NOT IMPLEMENTED"]
    direction TB
    WEB["Web App / Trigger"]:::future
    ORCH["[n8n] / Durable Orchestration"]:::future
    QW["Queue / Workers"]:::future
    AIP2["AI/Media Providers"]:::future
    OS["Object Storage"]:::future
    RQA["Render / QA"]:::future
    PUB["Publishing / Ad Platform"]:::future
    PIF["Performance Ingestion"]:::future
    FB["Feedback into Creative Intelligence"]:::future
    WEB -.-> ORCH -.-> QW -.-> AIP2 -.-> OS -.-> RQA -.-> PUB -.-> PIF -.-> FB
    FB -.->|"dashed feedback loop"| ORCH
  end

  subgraph CP["Production Control Plane — NOT IMPLEMENTED"]
    direction LR
    OBS["Observability"]:::future
    RET["Retries"]:::future
    IDEM["Idempotency"]:::future
    COST["Cost Tracking"]:::future
    ROUTE["Provider Routing"]:::future
  end

  CP -.-> ORCH
  CP -.-> QW
  CP -.-> AIP2
  CP -.-> RQA

  FS -.->|"production evolution"| WEB
```

**Evidence from the actual prototype:**
- The smoke-test run (`manifests/scenes/challenger_B_v2.json` via `python3 run.py compose ... --out state/smoke/B_EN_v2_smoke.mp4`) resolved the generated hook from the existing cached asset (`assets/generated/challenger_B_v2/hook_gen_v2.mp4`) with **`paid_calls_made=0`**, and left `final/B_EN_v2.mp4` byte-identical before/after (md5-verified).
- Challenger B v1 (face-forward reaction shot) **passed all technical QA but was rejected on human creative review** over an actor-identity mismatch with the real source footage.
- Challenger B v2 (POV bill-drop hook) was **frozen as "acceptable for experimental deployment; incremental creative value uncertain; requires performance validation"** — explicitly not declared a winner.
- The entire runtime (`run.py` + `src/*.py`) executes standalone via plain `python3` invocations with no Claude Code process in the loop — Claude Code appears in this diagram only as the development environment that built and hardened it, positioned outside `PROTO`.
- No object storage, queue, durable orchestrator, web trigger, or ad-platform integration exists in this repo — the entire right-hand production architecture and control plane are drawn FUTURE because none of it has been built.

---

## Architecture principle

> **AI proposes creative hypotheses; deterministic automation executes them; human and performance feedback decide what survives.**
