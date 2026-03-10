# comm_themes.py
# ─────────────────────────────────────────────────────────────
# Generates: communication_themes.csv
#
# Architecture:
#   - Operates on segment × PHASE (11-phase model from segment_goals.csv)
#   - Pulls allowed tones + hook taxonomy from allowed_tone_hook_matrix.json
#   - Calls local Ollama via llm.py (100% offline, no LangChain)
#   - Concurrency via concurrent.futures.ThreadPoolExecutor (max 2 threads)
#   - JSON schema validation + fallback via safe_parse_json
#   - Domain-agnostic: no hardcoded product names, tones, or drive names
#
# Inputs (all auto-loaded if not passed):
#   user_segments.csv             → segment behavioral stats
#   segment_goals.csv             → segment × phase goals  (goal_builder.py)
#   allowed_tone_hook_matrix.json → tones + hook taxonomy  (gen_tone_hook_matrix.py)
#
# Output:
#   communication_themes.csv      → one row per segment × phase
# ─────────────────────────────────────────────────────────────

import os
import json
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from llm         import llm, safe_parse_json, save_csv
from data_loader import load_data, add_derived_signals
from config      import OCTOLYSIS_DRIVES, OUTPUT_DIR_0


# ── Core LLM call — one segment × phase ──────────────────────

def _gen_theme_entry(
    segment_id:            str,
    segment_name:          str,
    lifecycle_stage:       str,
    phase_number:          int,
    phase_name:            str,
    day_range:             str,
    primary_goal:          str,
    sub_goal_1:            str,
    sub_goal_2:            str,
    dominant_propensity:   str,
    stats:                 dict,
    valid_tones:           list,
    valid_themes:          list,
    hook_taxonomy_context: str,
) -> dict:
    """
    One llm() call → one validated row for communication_themes.csv.
    JSON schema enforced via prompt constraints + safe_parse_json fallback.
    """
    themes_str = " | ".join(valid_themes)
    tones_str  = " | ".join(valid_tones)

    raw = llm(
        system=(
            "You are a lifecycle marketing strategist. "
            "Output ONLY a single valid JSON object — no markdown fences, "
            "no explanation, no extra keys."
        ),
        prompt=f"""
=== OCTOLYSIS HOOK DEFINITIONS ===
{hook_taxonomy_context}

=== ALLOWED VALUES (copy EXACTLY — no paraphrasing) ===
THEMES : {themes_str}
TONES  : {tones_str}

=== TARGET SEGMENT ===
segment_id          : {segment_id}
segment_name        : {segment_name}
dominant_propensity : {dominant_propensity}
avg_activeness      : {stats.get('activeness_score', 0.5):.2f}
avg_churn_risk      : {stats.get('churn_risk', 0.3):.2f}
avg_motivation      : {stats.get('motivation', 0.5):.2f}
avg_notif_open      : {stats.get('notif_open', 0.3):.2f}

=== CURRENT PHASE ===
phase_name   : {phase_name}
day_range    : {day_range}
primary_goal : {primary_goal}
sub_goal_1   : {sub_goal_1}
sub_goal_2   : {sub_goal_2}

Choose the most effective psychological themes and tone for this segment at this
phase, then write two punchy hook phrases (one English, one Hindi/Hinglish).

Return ONLY this JSON:
{{
  "primary_theme":   "<exact string from THEMES>",
  "secondary_theme": "<exact string from THEMES, different from primary>",
  "tone_preference": "<exact string from TONES>",
  "hook_en":         "<English hook — max 15 words, action-oriented>",
  "hook_hi":         "<Hindi/Hinglish hook — max 15 words, conversational>"
}}""",
    )

    fallback = {
        "primary_theme":   valid_themes[0],
        "secondary_theme": valid_themes[1] if len(valid_themes) > 1 else valid_themes[0],
        "tone_preference": valid_tones[0],
        "hook_en":         "Keep going — your progress is waiting!",
        "hook_hi":         "Aage badho — tumhari mehnat rang laayegi!",
    }
    result = safe_parse_json(raw, fallback=fallback)

    # ── Hard-enforce valid values post-parse ─────────────────
    primary   = result.get("primary_theme",   valid_themes[0])
    secondary = result.get("secondary_theme", valid_themes[1] if len(valid_themes) > 1 else valid_themes[0])
    tone      = result.get("tone_preference", valid_tones[0])

    if primary   not in valid_themes: primary   = valid_themes[0]
    if secondary not in valid_themes: secondary = valid_themes[0]
    if secondary == primary and len(valid_themes) > 1:
        secondary = next((t for t in valid_themes if t != primary), valid_themes[0])
    if tone not in valid_tones: tone = valid_tones[0]

    return {
        "segment_id":        segment_id,
        "segment_name":      segment_name,
        "lifecycle_stage":   lifecycle_stage,
        "phase_number":      phase_number,
        "phase_name":        phase_name,
        "day_range":         day_range,
        "primary_goal":      primary_goal,
        "primary_theme":     primary,
        "secondary_theme":   secondary,
        "tone_preference":   tone,
        "hook_en":           result.get("hook_en", fallback["hook_en"]),
        "hook_hi":           result.get("hook_hi", fallback["hook_hi"]),
    }


# ── Main entry point ──────────────────────────────────────────

def gen_communication_themes(
    user_segments_df:  Optional[pd.DataFrame] = None,
    segment_goals_df:  Optional[pd.DataFrame] = None,
    tone_hook_matrix:  Optional[dict]         = None,
    df:                Optional[pd.DataFrame] = None,
    output_dir:        Optional[str]          = None,
    max_workers:       int                    = 2,
) -> pd.DataFrame:
    """
    Build communication_themes.csv — one row per segment × phase.

    Args:
        user_segments_df  : user_segments.csv as DataFrame
        segment_goals_df  : segment_goals.csv as DataFrame (from goal_builder.py)
        tone_hook_matrix  : allowed_tone_hook_matrix.json as dict
        df                : raw behavioral DataFrame
        output_dir        : output directory override
        max_workers       : max concurrent Ollama threads (default 2)
    """
    print("\n[Task2-1/4] Generating: communication_themes.csv")

    # ── Load behavioral data ──────────────────────────────────
    if df is None:
        df = load_data()
        df = add_derived_signals(df)

    # ── Load user segments ────────────────────────────────────
    if user_segments_df is None:
        base_out = output_dir or OUTPUT_DIR_0
        seg_path = os.path.join(base_out, "user_segments.csv")
        if os.path.exists(seg_path):
            user_segments_df = pd.read_csv(seg_path)
        else:
            from segmentation_engine import gen_user_segments
            user_segments_df, _ = gen_user_segments(df, output_dir)

    # ── Load segment goals ────────────────────────────────────
    if segment_goals_df is None:
        base_out = output_dir or OUTPUT_DIR_0
        goals_path = os.path.join(base_out, "segment_goals.csv")
        if os.path.exists(goals_path):
            segment_goals_df = pd.read_csv(goals_path)
        else:
            from goal_builder import gen_segment_goals
            segment_goals_df = gen_segment_goals(
                user_segments_df=user_segments_df, df=df, output_dir=output_dir
            )

    # ── Load tone/hook matrix ─────────────────────────────────
    if tone_hook_matrix is None:
        base_out = output_dir or OUTPUT_DIR_0
        matrix_path = os.path.join(base_out, "allowed_tone_hook_matrix.json")
        if os.path.exists(matrix_path):
            with open(matrix_path, encoding="utf-8") as f:
                tone_hook_matrix = json.load(f)
        else:
            tone_hook_matrix = {}

    # ── Extract valid tones + themes ──────────────────────────
    valid_tones  = tone_hook_matrix.get("allowed_tones") or [
        "Motivational", "Encouraging", "Celebratory", "Urgent (mild)", "Friendly", "Informative"
    ]
    valid_themes = [d["name"] for d in OCTOLYSIS_DRIVES]

    hook_taxonomy_context = "".join(
        f"- {h['core_drive']}: {h['application']}\n"
        for h in tone_hook_matrix.get("hook_taxonomy", [])
    ) or "\n".join(f"- {d['name']}: {d['hook']}" for d in OCTOLYSIS_DRIVES)

    # ── Behavioral stats per segment ──────────────────────────
    rename_map = {
        "activeness_score":    "activeness_score",
        "churn_risk_score":    "churn_risk",
        "motivation_score":    "motivation",
        "notif_open_rate_30d": "notif_open",
    }
    agg_cols = {c: "mean" for c in rename_map if c in user_segments_df.columns}
    seg_stats = (
        user_segments_df.groupby("segment_id")
        .agg(agg_cols)
        .rename(columns=rename_map)
        .reset_index()
    )
    for col, default in [("activeness_score", 0.5), ("churn_risk", 0.3),
                          ("motivation", 0.5), ("notif_open", 0.3)]:
        if col not in seg_stats.columns:
            seg_stats[col] = default

    # ── Dominant propensity per segment ───────────────────────
    prop_col = "dominant_propensity" if "dominant_propensity" in user_segments_df.columns else None
    seg_meta = user_segments_df.groupby("segment_id").agg(
        segment_name=("segment_name", "first"),
        **({
            "dominant_propensity": (
                "dominant_propensity",
                lambda x: x.value_counts().idxmax()
            )
        } if prop_col else {})
    ).reset_index()
    if not prop_col:
        seg_meta["dominant_propensity"] = "unknown"

    # ── Merge onto deduplicated phase rows ────────────────────
    goals_deduped = (
        segment_goals_df
        .drop_duplicates(subset=["segment_id", "phase_name"])
        .sort_values(["segment_id", "phase_number"])
        .reset_index(drop=True)
    )

    merged = (
        goals_deduped
        .merge(seg_meta,  on="segment_id", how="left", suffixes=("", "_meta"))
        .merge(seg_stats, on="segment_id", how="left")
    )

    # Prefer segment_name from goals, fall back to meta column
    if "segment_name" not in merged.columns and "segment_name_meta" in merged.columns:
        merged.rename(columns={"segment_name_meta": "segment_name"}, inplace=True)

    for col, default in [("activeness_score", 0.5), ("churn_risk", 0.3),
                          ("motivation", 0.5), ("notif_open", 0.3)]:
        merged[col] = merged[col].fillna(default)

    total = len(merged)
    print(f"  {total} segment × phase combinations — max_workers={max_workers}\n")

    # ── Build job list ────────────────────────────────────────
    jobs = []
    for _, row in merged.iterrows():
        jobs.append({
            "segment_id":          str(row["segment_id"]),
            "segment_name":        str(row.get("segment_name", row["segment_id"])),
            "lifecycle_stage":     str(row.get("lifecycle_stage", "")),
            "phase_number":        int(row.get("phase_number", 0)),
            "phase_name":          str(row["phase_name"]),
            "day_range":           str(row.get("day_range", "")),
            "primary_goal":        str(row.get("primary_goal", "")),
            "sub_goal_1":          str(row.get("sub_goal_1", "")),
            "sub_goal_2":          str(row.get("sub_goal_2", "")),
            "dominant_propensity": str(row.get("dominant_propensity", "unknown")),
            "stats": {
                "activeness_score": float(row.get("activeness_score", 0.5)),
                "churn_risk":       float(row.get("churn_risk",       0.3)),
                "motivation":       float(row.get("motivation",       0.5)),
                "notif_open":       float(row.get("notif_open",       0.3)),
            },
        })

    # ── Concurrent Ollama calls ───────────────────────────────
    results_map: dict = {}

    def _run(idx: int, job: dict):
        return idx, _gen_theme_entry(
            segment_id            = job["segment_id"],
            segment_name          = job["segment_name"],
            lifecycle_stage       = job["lifecycle_stage"],
            phase_number          = job["phase_number"],
            phase_name            = job["phase_name"],
            day_range             = job["day_range"],
            primary_goal          = job["primary_goal"],
            sub_goal_1            = job["sub_goal_1"],
            sub_goal_2            = job["sub_goal_2"],
            dominant_propensity   = job["dominant_propensity"],
            stats                 = job["stats"],
            valid_tones           = valid_tones,
            valid_themes          = valid_themes,
            hook_taxonomy_context = hook_taxonomy_context,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run, idx, job): idx for idx, job in enumerate(jobs)}
        completed = 0
        for future in as_completed(futures):
            try:
                idx, result_row = future.result()
                results_map[idx] = result_row
                completed += 1
                j = jobs[idx]
                print(f"  [{completed}/{total}] ✓ {j['segment_id']} | {j['phase_name']}")
            except Exception as e:
                idx = futures[future]
                j   = jobs[idx]
                print(f"  [!] ✗ {j['segment_id']} | {j['phase_name']} — {e}")
                results_map[idx] = {
                    "segment_id":      j["segment_id"],
                    "segment_name":    j["segment_name"],
                    "lifecycle_stage": j["lifecycle_stage"],
                    "phase_number":    j["phase_number"],
                    "phase_name":      j["phase_name"],
                    "day_range":       j["day_range"],
                    "primary_goal":    j["primary_goal"],
                    "primary_theme":   valid_themes[0],
                    "secondary_theme": valid_themes[1] if len(valid_themes) > 1 else valid_themes[0],
                    "tone_preference": valid_tones[0],
                    "hook_en":         "Keep going — your progress is waiting!",
                    "hook_hi":         "Aage badho — tumhari mehnat rang laayegi!",
                }

    rows = [results_map[i] for i in range(len(jobs))]
    themes_df = pd.DataFrame(rows)
    save_csv(themes_df, "communication_themes.csv", output_dir)
    return themes_df


# ── Standalone runner ─────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Communication Themes Generator")
    parser.add_argument("--segments",   default="user_segments.csv",             help="user_segments.csv path")
    parser.add_argument("--goals",      default="segment_goals.csv",             help="segment_goals.csv path")
    parser.add_argument("--matrix",     default="allowed_tone_hook_matrix.json", help="tone/hook matrix JSON")
    parser.add_argument("--behavioral", default="user_behavioral_data.csv",      help="behavioral CSV path")
    parser.add_argument("--output-dir", default=".",                             help="output directory")
    parser.add_argument("--workers",    default=2, type=int,                     help="max concurrent Ollama threads")
    args = parser.parse_args()

    seg_df   = pd.read_csv(args.segments)    if os.path.exists(args.segments)   else None
    goals_df = pd.read_csv(args.goals)       if os.path.exists(args.goals)      else None
    beh_df   = pd.read_csv(args.behavioral)  if os.path.exists(args.behavioral) else None
    matrix   = None
    if os.path.exists(args.matrix):
        with open(args.matrix, encoding="utf-8") as f:
            matrix = json.load(f)

    os.makedirs(args.output_dir, exist_ok=True)

    out = gen_communication_themes(
        user_segments_df = seg_df,
        segment_goals_df = goals_df,
        tone_hook_matrix = matrix,
        df               = beh_df,
        output_dir       = args.output_dir,
        max_workers      = args.workers,
    )
    print(out[["segment_id", "phase_name", "primary_theme", "tone_preference", "hook_en"]].to_string(index=False))
