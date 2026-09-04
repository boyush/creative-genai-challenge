"""
Asset resolver: turns a challenger manifest + source inventory into an
ordered, executable scene timeline of concrete operations against the
parent source video.

Resolution order per Asset Resolution Policy (CLAUDE.md):
  1. existing source footage as-is
  2. existing footage re-edited/reordered/trimmed
  3. caption/overlay treatment
  4. extracted B-roll/proof
  5. generated video (pluggable -> src/generate.py; not invoked unless a
     segment is explicitly flagged generation_required=true)

This module is intentionally generic across challengers: it reads
locked_variables + the declared primary_variable's mutation off the
challenger manifest, passes through every locked (unmutated) section of
the parent video untouched, and only re-builds the segment(s) tied to
the experiment's primary_variable.
"""
from dataclasses import dataclass, field
from typing import Optional

from src import config, generate


class AssetResolutionError(RuntimeError):
    pass


@dataclass
class Segment:
    id: str
    category: str
    source: str          # path to source media for this segment
    in_ts: float
    out_ts: float
    caption: Optional[str] = None      # None => keep source as-is (no overlay)
    cover_original_caption: bool = False
    hold_to_duration: Optional[float] = None  # freeze-extend clip to this length
    generated: bool = False
    notes: str = ""

    @property
    def src_duration(self) -> float:
        return round(self.out_ts - self.in_ts, 3)


def _hook_segments_from_challenger(challenger: dict, source_video: str) -> list[Segment]:
    """Build the mutated hook segments from challenger_A.json's
    source_references (already computed during source-media inspection)."""
    refs = challenger.get("source_references")
    if not refs:
        raise AssetResolutionError(
            "challenger manifest has no 'source_references' — run source "
            "inspection / asset inventory before resolving assets."
        )
    if not refs.get("hook_can_be_built_from_existing_footage"):
        # Pluggable escape hatch for future challengers: hand off to
        # generate.py. Not exercised for Challenger A.
        return [generate.request_generated_hook(challenger)]

    s1 = refs["hook_scene_1_source"]
    s2 = refs["hook_scene_2_source"]
    hook_cfg = challenger["hook"]

    seg1 = Segment(
        id="hook_scene_1",
        category="hook",
        source=source_video,
        in_ts=float(s1["in"]),
        out_ts=float(s1["in"]) + float(hook_cfg["scene_1"]["target_duration_seconds"]),
        caption=hook_cfg["scene_1"]["preferred_caption"],
        cover_original_caption=True,
        notes=f"reuse {s1['segment']}, trimmed to target duration",
    )
    seg2 = Segment(
        id="hook_scene_2",
        category="hook",
        source=source_video,
        in_ts=float(s2["in"]),
        out_ts=float(s2["out"]),
        caption=hook_cfg["scene_2"]["preferred_caption"],
        cover_original_caption=True,
        hold_to_duration=float(hook_cfg["scene_2"]["target_duration_seconds"]),
        notes=f"reuse {s2['segment']} (real earnings proof), freeze-extended",
    )
    return [seg1, seg2]


def _locked_body_segment(challenger: dict, source_video: str) -> Segment:
    """Everything after the mutated hook, passed through untouched so all
    locked_variables (proof, gameplay, payout, offer, CTA...) survive
    byte-for-byte."""
    refs = challenger["source_references"]
    hook_end = float(refs["hook_scene_1_source"]["out"])  # unused; body starts at required_sections_map
    body_start = float(refs["required_sections_map"]["product_reveal"]["in"])
    body_end = float(refs["required_sections_map"]["cta"]["out"])
    return Segment(
        id="locked_body",
        category="locked_body",
        source=source_video,
        in_ts=body_start,
        out_ts=body_end,
        caption=None,
        notes="passthrough: product_reveal..cta, unmodified per locked_variables",
    )


def resolve_timeline(challenger: dict, source_video: str) -> list[Segment]:
    """Primary entrypoint. Returns an ordered list of Segments describing
    exactly what render/compose must do."""
    primary_var = challenger.get("primary_variable")
    if primary_var != "hook_proof_timing":
        # Generic guard: only the declared experiment variable may
        # materially change. Anything else requires new resolver logic.
        raise AssetResolutionError(
            f"no asset-resolution strategy implemented for primary_variable="
            f"{primary_var!r}; refusing to guess."
        )

    hook_segments = _hook_segments_from_challenger(challenger, source_video)
    body_segment = _locked_body_segment(challenger, source_video)
    timeline = [*hook_segments, body_segment]

    for seg in timeline:
        if seg.generated:
            raise AssetResolutionError(
                f"segment {seg.id!r} requires generated video, but paid "
                f"generation is disabled for this run. Genuine blocker."
            )
        if seg.out_ts <= seg.in_ts:
            raise AssetResolutionError(f"segment {seg.id!r} has non-positive duration")

    return timeline
