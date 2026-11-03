"""mvm — SongWeave command line.

Local commands (init-manifest, analyze, export, validate-export, serve, status) never call a
generation API. Only `mvm generate ...` can contact the Meta Model API, and only for the
explicitly selected items.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config


def _ids(value: str | None) -> list[str] | None:
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


def cmd_init_manifest(args, cfg) -> int:
    from .manifest import init_manifest

    out = Path(args.out) if args.out else cfg.manifest_path
    lyrics_dir = Path(args.lyrics_dir) if args.lyrics_dir else None
    doc, added, attached = init_manifest(
        out,
        Path(args.audio_dir),
        lyrics_dir,
        args.lang or cfg.section("backends", "lyrics_sonar")["default_lang"],
        args.name,
        update=args.update,
    )
    print(f"manifest: {out} ({len(doc['tracks'])} tracks, {len(added)} added, lyrics attached to {len(attached)})")
    return 0


def cmd_analyze(args, cfg) -> int:
    from .analyze import Analyzer
    from .manifest import check_files, load_manifest

    manifest = load_manifest(Path(args.manifest) if args.manifest else cfg.manifest_path)
    problems = check_files(manifest)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2
    backends = tuple(args.backends.split(",")) if args.backends else ("peav", "merit", "sonar")
    summary = Analyzer(cfg, manifest, force=args.force, device=args.device).run(_ids(args.tracks), backends)
    print(f"analysis finished in {summary['wall_seconds']}s")
    return 0


def cmd_export(args, cfg) -> int:
    from .export.build import build_export

    path = build_export(cfg, Path(args.manifest) if args.manifest else None, log=print)
    print(f"export written: {path}")
    return 0


def cmd_validate_export(args, cfg) -> int:
    from .export.validate import validate_export_dir

    errors, warnings = validate_export_dir(Path(args.dir) if args.dir else cfg.export_dir)
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print("export validation:", "PASS" if not errors else f"FAIL ({len(errors)} error(s))")
    return 0 if not errors else 1


def cmd_serve(args, cfg) -> int:
    from .serve import serve

    serve(cfg, host=args.host, port=args.port)
    return 0


def cmd_status(args, cfg) -> int:
    from .status import status_report

    print(json.dumps(status_report(cfg), ensure_ascii=False, indent=2))
    return 0


def cmd_generate(args, cfg) -> int:
    from .interpretations.jobs import run_generate

    return run_generate(cfg, args)


def cmd_review(args, cfg) -> int:
    from .interpretations.cache import set_review

    status = "approved" if args.approve else "rejected" if args.reject else "unreviewed"
    rec = set_review(cfg, args.interpretation_id, status, args.reviewer, args.note)
    print(f"{rec['interpretation_id']}: review={rec['review']['status']}")
    if args.refresh_export:
        from .export.build import write_interpretations

        write_interpretations(cfg)
    return 0


def cmd_probe(args, cfg) -> int:
    from .probe import run_probe

    return run_probe(cfg, args.target)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mvm", description="SongWeave — explore how songs connect, in sound and meaning.")
    p.add_argument("--config", help="path to songweave.toml (default: config/songweave.toml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init-manifest", help="scan an audio folder into a manifest with stable track IDs")
    s.add_argument("audio_dir")
    s.add_argument("--out")
    s.add_argument("--lyrics-dir", help="folder with <audio stem>.txt original lyrics")
    s.add_argument("--lang", help="SONAR language code for found lyrics, e.g. jpn_Jpan")
    s.add_argument("--name", default="Local library")
    s.add_argument("--update", action="store_true", help="add new files to an existing manifest")
    s.set_defaults(func=cmd_init_manifest)

    s = sub.add_parser("analyze", help="run local model inference (PE-AV, MERIT, SONAR)")
    s.add_argument("--manifest")
    s.add_argument("--tracks", help="comma-separated track IDs (default: all)")
    s.add_argument("--backends", help="comma-separated subset of peav,merit,sonar")
    s.add_argument("--device", choices=["cpu", "mps"], help="override analysis.device")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_analyze)

    s = sub.add_parser("export", help="compute relations/evidence/map and write the local web bundle")
    s.add_argument("--manifest")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("validate-export", help="check a written export bundle")
    s.add_argument("--dir")
    s.set_defaults(func=cmd_validate_export)

    s = sub.add_parser("serve", help="serve web/dist and the export on localhost (HTTP Range for audio)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("status", help="report analysis coverage, export and interpretation state")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("probe", help="non-song checks: meta (API auth + structured output), sonar")
    s.add_argument("target", choices=["meta", "sonar"])
    s.set_defaults(func=cmd_probe)

    g = sub.add_parser("generate", help="explicit Meta Model API jobs (cached)")
    gsub = g.add_subparsers(dest="task", required=True)
    for name, helptext in (("understand-lyrics", "interpret selected tracks' original lyrics"), ("explain", "explain selected song pairs")):
        s = gsub.add_parser(name, help=helptext)
        if name == "understand-lyrics":
            s.add_argument("--tracks", required=True, help="comma-separated track IDs")
        else:
            grp = s.add_mutually_exclusive_group(required=True)
            grp.add_argument("--pairs", help="comma-separated A:B track ID pairs")
            grp.add_argument("--all-pairs", action="store_true", help="every pair in the current export (still needs --max-items)")
        s.add_argument("--allow-lyrics-upload", action="store_true", help="permit sending lyrics / lyric-derived content for this invocation")
        s.add_argument("--dry-run", action="store_true", help="show the outbound payload scope; send nothing")
        s.add_argument("--max-items", type=int, help="raise the per-job item cap (never silently truncated)")
        s.add_argument("--force", action="store_true", help="regenerate even if a cached result exists")
        s.add_argument("--model", help="override meta_api.model")
        s.add_argument("--lang", choices=["en", "ja", "zh-Hans"], help="language of the generated text (default: meta_api.output_language)")
        s.add_argument("--workers", type=int, default=1, help="parallel API requests (default 1)")
        s.set_defaults(func=cmd_generate)

    s = sub.add_parser("review", help="record human review of a cached interpretation")
    s.add_argument("interpretation_id")
    grp = s.add_mutually_exclusive_group(required=True)
    grp.add_argument("--approve", action="store_true")
    grp.add_argument("--reject", action="store_true")
    grp.add_argument("--reset", action="store_true")
    s.add_argument("--reviewer", default="owner")
    s.add_argument("--note")
    s.add_argument("--no-refresh-export", dest="refresh_export", action="store_false")
    s.set_defaults(func=cmd_review)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(Path(args.config) if args.config else None)
    return int(args.func(args, cfg) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
