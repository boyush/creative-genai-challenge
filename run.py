#!/usr/bin/env python3
"""
Thin executable entrypoint wiring the reusable pipeline modules:

  manifest -> validate -> resolve assets -> generate/reuse -> compose -> QA -> state/lineage

This is the prototype-runtime CLI described in README.md ("Prototype
runtime" section) -- a manual/scripted entrypoint, not a production
orchestrator. Claude Code drove development of this pipeline but is not
part of running it: this script executes standalone via `python3 run.py
...` with no dependency on an assistant session.

Examples:
  python3 run.py validate manifests/scenes/challenger_B_v2.json
  python3 run.py compose manifests/scenes/challenger_B_v2.json \\
      --out state/smoke/B_EN_v2_smoke.mp4 \\
      --expected manifests/scenes/challenger_B_v2.expected.json \\
      --challenger B_v2_smoke
  python3 run.py qa final/A_EN.mp4
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import compose, qa, state, manifest, config, generate  # noqa: E402


def _load_expected(path: str | None) -> dict | None:
    if not path:
        return None
    return json.loads(Path(path).read_text())


def cmd_validate(args: argparse.Namespace) -> None:
    try:
        data = manifest.load_scene_manifest(Path(args.manifest))
    except manifest.ManifestError as e:
        print(f"INVALID: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"VALID: {args.manifest} ({len(data['segments'])} segment(s), output={data['output']})")


def cmd_compose(args: argparse.Namespace) -> None:
    output_override = Path(args.out) if args.out else None

    try:
        result = compose.compose(
            Path(args.manifest),
            output_override=output_override,
            allow_paid_call=args.allow_paid_call,
        )
    except manifest.ManifestError as e:
        print(f"MANIFEST INVALID: {e}", file=sys.stderr)
        sys.exit(2)
    except generate.GenerationDisabled as e:
        print(f"BLOCKED (no cached asset, paid call not enabled): {e}", file=sys.stderr)
        sys.exit(3)
    except generate.GenerationError as e:
        print(f"GENERATION FAILED: {e}", file=sys.stderr)
        sys.exit(3)
    except compose.ComposeError as e:
        print(f"COMPOSE FAILED: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, indent=2))
    print(f"paid_calls_made={result['paid_calls_made']}", file=sys.stderr)

    qa_result = qa.run_qa(Path(result["output"]), expected=_load_expected(args.expected))
    print(json.dumps(qa_result, indent=2))

    if args.challenger:
        state.mark(args.challenger, "compose", "completed", output=result["output"],
                    paid_calls_made=result["paid_calls_made"])
        state.mark(args.challenger, "qa", "completed" if qa_result["technical"]["pass"] else "failed")
        lineage_path = config.REPORTS_DIR / f"{args.challenger}_scene_lineage.json"
        lineage_path.parent.mkdir(parents=True, exist_ok=True)
        lineage_path.write_text(json.dumps({"compose": result, "qa": qa_result}, indent=2))
        print(f"lineage -> {lineage_path}", file=sys.stderr)

    sys.exit(0 if qa_result["technical"]["pass"] else 1)


def cmd_qa(args: argparse.Namespace) -> None:
    result = qa.run_qa(Path(args.input), expected=_load_expected(args.expected))
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["technical"]["pass"] else 1)


def main() -> None:
    p = argparse.ArgumentParser(description="Almedia Creative Factory -- prototype pipeline CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    pv = sub.add_parser("validate", help="validate a scene manifest and exit (no generation/render)")
    pv.add_argument("manifest")
    pv.set_defaults(func=cmd_validate)

    pc = sub.add_parser("compose", help="validate -> resolve/generate (cache-first) -> render -> QA")
    pc.add_argument("manifest")
    pc.add_argument("--out", help="override output path, e.g. for a smoke test that must not touch final/")
    pc.add_argument("--expected", help="path to a JSON dict of expected QA values")
    pc.add_argument("--challenger", help="id to tag state/ and reports/ lineage output with")
    pc.add_argument("--allow-paid-call", action="store_true", dest="allow_paid_call",
                     help="permit a live provider call for segments with no cached asset (default: off)")
    pc.set_defaults(func=cmd_compose)

    pq = sub.add_parser("qa", help="run technical QA against an existing rendered file")
    pq.add_argument("input")
    pq.add_argument("--expected", help="path to a JSON dict of expected QA values")
    pq.set_defaults(func=cmd_qa)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
