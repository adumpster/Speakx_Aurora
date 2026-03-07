# goal_builder.py
# ─────────────────────────────────────────────────────────────
# Generates: segment_goals.csv
#
# For each segment × lifecycle_stage combination found in the data:
#   - Define primary goal, sub-goals
#   - Map to day-on-day progression (D0→D1→D2...)
#   - One LLM call per combination
# ─────────────────────────────────────────────────────────────

import pandas as pd
from llm import llm, safe_parse_json, save_csv
from data_loader import load_data, add_derived_signals
from kb_loader   import load_kb
from config import LIFECYCLE_STAGES


def _gen_goal_entry(
    segment_id:      str,
    segment_name:    str,
    lifecycle_stage: str,
    stage_info:      dict,
    segment_stats:   dict,
    north_star:      dict,
) -> dict:
    """One LLM call → one row for segment_goals.csv."""

    ns_metric = north_star.get("inferred_north_star", {}).get("metric_name", "W1 Retention")
    ns_def    = north_star.get("inferred_north_star", {}).get("definition", "")

    raw = llm(
        system="You are a product journey designer. Output ONLY valid JSON.",
        prompt=f"""
KNOWLEDGE BANK:
{load_kb()}

Segment : {segment_name} (id: {segment_id})
Lifecycle stage : {lifecycle_stage} ({stage_info['day_range']})
Stage primary goal : {stage_info['primary_goal']}

Segment stats (from behavioral data):
  avg_activeness_score : {segment_stats.get('avg_activeness', 0.5)}
  avg_churn_risk       : {segment_stats.get('avg_churn_risk', 0.3)}
  avg_motivation       : {segment_stats.get('avg_motivation', 0.5)}
  avg_exercises_7d     : {segment_stats.get('avg_exercises', 5)}

North Star Metric: {ns_metric} — {ns_def}

Use the Knowledge Bank above for company context, product features, and user journey stages.
Design the goal progression for this segment × lifecycle stage.
Return ONLY valid JSON:
{{
  "primary_goal":     "<the single most important goal to drive for this combination>",
  "sub_goals":        ["<sub goal 1>", "<sub goal 2>", "<sub goal 3>"],
  "day_focus": {{
    "D0": "<what to nudge user to do on first notification day>",
    "D1": "<Day 1 focus>",
    "D2": "<Day 2 focus>",
    "D3-D5": "<Mid-period focus>",
    "D6-D7": "<End-of-period focus>"
  }},
  "success_metric":   "<what measurable outcome signals this goal was achieved>",
  "failure_signal":   "<what behavioural signal means this goal is failing>",
  "escalation_action":"<what to do if failure signal is detected>"
}}"""
    )

    result = safe_parse_json(raw, fallback={
        "primary_goal":      stage_info["primary_goal"],
        "sub_goals":         ["Increase session frequency", "Complete at least 1 exercise/day", "Maintain streak"],
        "day_focus":         {"D0": "First practice session", "D1-D7": "Build daily habit"},
        "success_metric":    "exercises_completed_7d >= 3",
        "failure_signal":    "sessions_last_7d == 0 for 3 consecutive days",
        "escalation_action": "Send Loss Avoidance notification with streak-save hook",
    })

    return {
        "segment_id":        segment_id,
        "segment_name":      segment_name,
        "lifecycle_stage":   lifecycle_stage,
        "day_range":         stage_info["day_range"],
        "primary_goal":      result.get("primary_goal", stage_info["primary_goal"]),
        "sub_goal_1":        result.get("sub_goals", [""])[0] if result.get("sub_goals") else "",
        "sub_goal_2":        result.get("sub_goals", ["",""])[1] if len(result.get("sub_goals",[])) > 1 else "",
        "sub_goal_3":        result.get("sub_goals", ["","",""])[2] if len(result.get("sub_goals",[])) > 2 else "",
        "day_focus_D0":      result.get("day_focus", {}).get("D0", ""),
        "day_focus_D1":      result.get("day_focus", {}).get("D1", ""),
        "day_focus_D2":      result.get("day_focus", {}).get("D2", ""),
        "day_focus_D3_D5":   result.get("day_focus", {}).get("D3-D5", ""),
        "day_focus_D6_D7":   result.get("day_focus", {}).get("D6-D7", ""),
        "success_metric":    result.get("success_metric", ""),
        "failure_signal":    result.get("failure_signal", ""),
        "escalation_action": result.get("escalation_action", ""),
    }


def gen_segment_goals(
    user_segments_df: pd.DataFrame = None,
    df: pd.DataFrame = None,
    north_star: dict = None,
    output_dir: str = None,
) -> pd.DataFrame:
    """
    Build segment_goals.csv.

    Args:
        user_segments_df : output of gen_user_segments (optional)
        df               : raw behavioral DataFrame (optional)
        north_star       : output of gen_north_star (optional)
        output_dir       : override output directory (optional)
    """
    print("\n[5/5] Generating: segment_goals.csv")

    # Load raw data if needed for stats
    if df is None:
        df = load_data()
        df = add_derived_signals(df)

    if north_star is None:
        north_star = {
            "inferred_north_star": {
                "metric_name": "W1 Retention",
                "definition":  "Users completing at least one exercise in week 1 post-conversion.",
            }
        }

    # Determine segment × stage combinations
    if user_segments_df is not None and "segment_id" in user_segments_df.columns:
        combos = (
            user_segments_df[["segment_id", "segment_name", "lifecycle_stage"]]
            .drop_duplicates()
            .sort_values(["segment_id", "lifecycle_stage"])
        )
    else:
        # Fallback: re-run segmentation inline
        from segmentation_engine import gen_user_segments
        user_segments_df, _ = gen_user_segments(df, output_dir)
        combos = (
            user_segments_df[["segment_id", "segment_name", "lifecycle_stage"]]
            .drop_duplicates()
            .sort_values(["segment_id", "lifecycle_stage"])
        )

    rows = []
    total = len(combos)
    for i, (_, combo) in enumerate(combos.iterrows()):
        sid   = combo["segment_id"]
        sname = combo["segment_name"]
        stage = combo["lifecycle_stage"]

        stage_info = LIFECYCLE_STAGES.get(stage, {
            "day_range": "D0+", "primary_goal": "Engage user"
        })

        # Compute stats for this segment from the behavioral data
        seg_df = df[df["lifecycle_stage"] == stage] if user_segments_df is None else \
                 df[df["user_id"].isin(user_segments_df[user_segments_df["segment_id"] == sid]["user_id"])]

        stats = {
            "avg_activeness": round(seg_df["activeness_score"].mean(), 3) if "activeness_score" in seg_df.columns else 0.5,
            "avg_churn_risk": round(seg_df["churn_risk_score"].mean(), 3) if "churn_risk_score" in seg_df.columns else 0.3,
            "avg_motivation": round(seg_df["motivation_score"].mean(), 3),
            "avg_exercises":  round(seg_df["exercises_completed_7d"].mean(), 1),
        }

        print(f"  [{i+1}/{total}] {sid} × {stage}")
        row = _gen_goal_entry(sid, sname, stage, stage_info, stats, north_star)
        rows.append(row)

    goals_df = pd.DataFrame(rows)
    save_csv(goals_df, "segment_goals.csv", output_dir)
    return goals_df
