# main.py
# ─────────────────────────────────────────────────────────────
# USAGE:
#   python main.py                     # full pipeline (task1 + task2)
#   python main.py --steps north_star  # single step
#   python main.py --steps task1       # all Task 1 steps
#   python main.py --steps task2       # all Task 2 steps
#   python main.py --steps task3       # learning engine (needs experiment_results.csv)
#   python main.py --list              # list all steps
#   python main.py --data my_data.csv  # custom CSV
# ─────────────────────────────────────────────────────────────

import argparse
import os
import sys
import json
import pandas as pd

from config import USER_DATA_PATH, OUTPUT_DIR_0, OUTPUT_DIR_1

STEPS = {
    "north_star":  "Generate company_north_star.json",
    "features":    "Generate feature_goal_map.json",
    "tone_matrix": "Generate allowed_tone_hook_matrix.json",
    "segments":    "Generate user_segments.csv",
    "goals":       "Generate segment_goals.csv",
    "themes":      "Generate communication_themes.csv",
    "templates":   "Generate message_templates.csv",
    "timing":      "Generate timing_recommendations.csv",
    "schedule":    "Generate user_notification_schedule.csv",
    "learning":    "Task 3 learning engine (needs experiment_results.csv)",
}

ALIASES = {
    "task1": ["north_star", "features", "tone_matrix", "segments", "goals"],
    "task2": ["themes", "templates", "timing", "schedule"],
    "task3": ["learning"],
    "all":   ["north_star", "features", "tone_matrix", "segments", "goals",
               "themes", "templates", "timing", "schedule"],  # learning excluded from 'all'
}

state = {}


def _df_or_load(key: str, folder: str, filename: str):
    """
    Safe DataFrame retrieval from state or disk.
    Fixes the 'truth value of DataFrame is ambiguous' error
    that happens when you do `state.get(...) or load_csv(...)`.
    """
    val = state.get(key)
    if val is not None and isinstance(val, pd.DataFrame) and not val.empty:
        return val
    return _load_csv(folder, filename)


def _load_json(folder: str, filename: str) -> dict:
    path = os.path.join(folder, filename)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    print(f"  [warn] {path} not found — using empty fallback")
    return {}


def _load_csv(folder: str, filename: str):
    path = os.path.join(folder, filename)
    if os.path.exists(path):
        return pd.read_csv(path)
    print(f"  [warn] {path} not found — step will regenerate")
    return None


def run_step(name: str, profile, out0: str):
    """
    profile  → DataProfile object  (has .df, .summary, .feature_cols etc.)
    profile.df → the cleaned + scored pandas DataFrame
    out0     → output directory string
    """
    print(f"\n{'='*60}")
    print(f"  STEP: {name.upper()}")
    print(f"{'='*60}")

    # ── Task 1 ──────────────────────────────────────────────

    if name == "north_star":
        from gen_north_star import gen_north_star
        state["north_star"] = gen_north_star(profile, out0)

    elif name == "features":
        from gen_feature_goal_map import gen_feature_goal_map
        ns = state.get("north_star") or _load_json(out0, "company_north_star.json")
        state["features"] = gen_feature_goal_map(profile, ns, out0)

    elif name == "tone_matrix":
        from gen_tone_hook_matrix import gen_tone_hook_matrix
        state["tone_matrix"] = gen_tone_hook_matrix(profile, out0)

    elif name == "segments":
        from segmentation_engine import gen_user_segments
        user_seg_df, seg_summary_df = gen_user_segments(profile.df, out0)
        state["user_segments"] = user_seg_df
        state["seg_summary"]   = seg_summary_df

    elif name == "goals":
        from goal_builder import gen_segment_goals
        ns       = state.get("north_star") or _load_json(out0, "company_north_star.json")
        user_seg = _df_or_load("user_segments", out0, "user_segments.csv")
        fgm      = state.get("features")   or _load_json(out0, "feature_goal_map.json")
        tm       = state.get("tone_matrix") or _load_json(out0, "allowed_tone_hook_matrix.json")
        state["goals"] = gen_segment_goals(user_seg, profile.df, ns, out0, fgm, tm)

    # ── Task 2 ──────────────────────────────────────────────

    elif name == "themes":
        from comm_themes import gen_communication_themes
        user_seg  = _df_or_load("user_segments", out0, "user_segments.csv")
        seg_goals = _df_or_load("goals",         out0, "segment_goals.csv")
        state["themes"] = gen_communication_themes(user_seg, seg_goals, df=profile.df, output_dir=out0)

    elif name == "templates":
        from message_template_gen import gen_message_templates
        themes   = _df_or_load("themes",        out0, "communication_themes.csv")
        goals    = _df_or_load("goals",         out0, "segment_goals.csv")
        user_seg = _df_or_load("user_segments", out0, "user_segments.csv")
        state["templates"] = gen_message_templates(themes, goals, user_seg, profile.df, output_dir=out0)

    elif name == "timing":
        from timing_optimizer import gen_timing_recommendations
        user_seg = _df_or_load("user_segments", out0, "user_segments.csv")
        state["timing"] = gen_timing_recommendations(user_seg, profile.df, out0)

    elif name == "schedule":
        from notification_scheduler import run_pipeline
        run_pipeline()
        out_path = os.path.join(out0, "user_notification_schedule.csv")
        if os.path.exists(out_path):
            state["schedule"] = pd.read_csv(out_path)

    # ── Task 3 ──────────────────────────────────────────────

    elif name == "learning":
        from learning_engine import run_learning_engine
        tmpl_path   = os.path.join(out0, "message_templates.csv")
        timing_path = os.path.join(out0, "timing_recommendations.csv")
        state["iter1_templates"], state["delta_report"] = run_learning_engine(
            tmpl_path, timing_path, OUTPUT_DIR_1
        )

    else:
        print(f"  [warn] Unknown step: '{name}' — skipping")


def resolve_steps(requested: list) -> list:
    expanded = []
    for s in requested:
        if s in ALIASES:
            expanded.extend(ALIASES[s])
        elif s in STEPS:
            expanded.append(s)
        else:
            print(f"  [warn] Unknown step/alias: '{s}' — ignoring")
    seen, ordered = set(), []
    for s in expanded:
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    return ordered


def main():
    parser = argparse.ArgumentParser(description="Project Aurora — Notification Orchestrator")
    parser.add_argument("--steps", nargs="+", default=["all"], metavar="STEP",
                        help="Steps: " + ", ".join(list(STEPS.keys()) + list(ALIASES.keys())))
    parser.add_argument("--data",  default=USER_DATA_PATH, metavar="CSV")
    parser.add_argument("--out0",  default=OUTPUT_DIR_0,   metavar="DIR")
    parser.add_argument("--list",  action="store_true",    help="List steps and exit")
    args = parser.parse_args()

    if args.list:
        print("\nSteps:")
        for k, v in STEPS.items():
            print(f"  {k:14s}: {v}")
        print("\nAliases:")
        for k, v in ALIASES.items():
            print(f"  {k:14s}: {v}")
        sys.exit(0)

    print(f"\nProject Aurora — Starting pipeline")
    print(f"  Data:   {args.data}")
    print(f"  Output: {args.out0}")

    from data_loader import load_and_profile
    try:
        profile = load_and_profile(args.data)
    except Exception as e:
        print(f"\n[ERROR] Could not load '{args.data}': {e}")
        sys.exit(1)

    os.makedirs(args.out0, exist_ok=True)

    steps_to_run = resolve_steps(args.steps)
    print(f"\n  Steps to run: {steps_to_run}\n")

    failed = []
    for step in steps_to_run:
        try:
            run_step(step, profile, args.out0)
        except Exception as e:
            failed.append(step)
            print(f"\n[ERROR] Step '{step}' failed: {e}")
            import traceback
            traceback.print_exc()
            print(f"  Continuing...\n")

    print(f"\n{'='*60}")
    print(f"  Done! Outputs → {args.out0}/")
    if failed:
        print(f"  Failed steps: {failed}")
    else:
        print(f"  All steps completed successfully.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()