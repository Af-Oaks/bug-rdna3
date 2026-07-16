"""Create a thesis-friendly per-game capture session."""

from __future__ import annotations

import argparse

from scripts.analysis_pipeline.common.session_lib import initialize_session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, help="Game slug, e.g. cyberpunk2077")
    parser.add_argument("--scene", required=True, help="Scene slug, e.g. market_square_noon")
    parser.add_argument("--settings-profile", required=True, help="Graphics settings profile label")
    parser.add_argument("--operator-notes", default="", help="Short operator note to seed the session")
    parser.add_argument(
        "--comparison-cohort",
        default="unclassified",
        help="Comparison grouping such as high_gain_group or low_gain_group",
    )
    parser.add_argument("--proton-version", default="", help="Proton version used for the run")
    parser.add_argument("--mesa-build-info", default="", help="Mesa commit, package, or local build label")
    parser.add_argument("--radv-build-info", default="", help="RADV build description if known")
    parser.add_argument("--aco-variant-tag", default="", help="ACO or fork tag for future comparison")
    parser.add_argument(
        "--compiler-variant-tag",
        default="baseline",
        help="Overall compiler variant tag such as baseline or aco_custom",
    )
    parser.add_argument(
        "--session-timestamp",
        default="",
        help="Override timestamp in YYYYMMDD_HHMMSS format for reproducible naming",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = initialize_session(
        game_slug=args.game,
        scene_slug=args.scene,
        settings_profile=args.settings_profile,
        operator_notes=args.operator_notes,
        comparison_cohort=args.comparison_cohort,
        proton_version=args.proton_version or None,
        mesa_build_info=args.mesa_build_info or None,
        radv_build_info=args.radv_build_info or None,
        aco_variant_tag=args.aco_variant_tag or None,
        compiler_variant_tag=args.compiler_variant_tag or None,
        timestamp=args.session_timestamp or None,
    )
    print(f"Created session: {result['session_id']}")
    print(f"Session root: {result['session_root']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
