# timing_optimizer.py
# ─────────────────────────────────────────────────────────────
# Generates:
#   - timing_recommendations.csv  (optimal windows per segment)
#   - user_notification_schedule.csv  (per-user daily schedule)
#
# Logic:
#   - Map preferred_hour → time window bucket per user
#   - Score each window per segment using notif_open_rate_30d
#   - Apply frequency guardrails (activeness → notifs/day)
#   - Use LLM to enhance recommendations with reasoning
# ─────────────────────────────────────────────────────────────

import pandas as pd
import numpy as np
from llm import llm, safe_parse_json, save_csv
from data_loader import load_data, add_derived_signals
from kb_loader   import load_kb
from config import TIME_WINDOWS, FREQ_BANDS

NOTIFS_PER_DAY_MAX = 9
NOTIFS_PER_DAY_MIN = 3
UNINSTALL_GUARDRAIL_THRESHOLD = 0.02  # 2% → reduce by 2


def _hour_to_window(hour: int) -> str:
    """Map a preferred_hour (0-23) to the matching time window name."""
    if 6 <= hour <= 8:
        return "early_morning"
    elif 9 <= hour <= 11:
        return "mid_morning"
    elif 12 <= hour <= 14:
        return "afternoon"
    elif 15 <= hour <= 17:
        return "late_afternoon"
    elif 18 <= hour <= 20:
        return "evening"
    elif 21 <= hour <= 23:
        return "night"
    else:
        return "early_morning"  # default for early-hours users (0-5)


def _get_notifs_per_day(activeness: float) -> int:
    """Return notification count based on activeness score band."""
    for band in FREQ_BANDS:
        if band["min"] <= activeness <= band["max"]:
            lo, hi = band["notifs_per_day_range"]
            return int((lo + hi) / 2)
    return NOTIFS_PER_DAY_MIN


def _build_schedule_for_user(
    user: pd.Series,
    templates_pool: list[str],
    segment_windows: list[str],
) -> list[dict]:
    """
    Build notif_1 … notif_9 rows for a single user.
    Returns list of dicts with (notif_slot, template_id, time_window, channel).
    """
    n_notifs = _get_notifs_per_day(user.get("activeness_score", 0.5))

    # Build ordered window list: start from user's preferred window, cycle rest
    user_window = _hour_to_window(int(user.get("preferred_hour", 9)))
    window_order = [w["name"] for w in TIME_WINDOWS]

    # Rotate so preferred window is first; then fill from segment optimal windows
    preferred_idx = window_order.index(user_window) if user_window in window_order else 0
    ordered = window_order[preferred_idx:] + window_order[:preferred_idx]

    slots = []
    for i in range(1, n_notifs + 1):
        window = ordered[(i - 1) % len(ordered)]
        tid    = templates_pool[(i - 1) % len(templates_pool)] if templates_pool else f"template_{i}"
        slots.append({
            "notif_slot":  f"notif_{i}",
            "template_id": tid,
            "time_window": window,
            "channel":     "push_notification",
        })
    return slots


def gen_timing_recommendations(
    user_segments_df: pd.DataFrame = None,
    df: pd.DataFrame = None,
    output_dir: str = None,
) -> pd.DataFrame:
    """
    Build timing_recommendations.csv.
    One row per segment × lifecycle_stage with optimal window order + CTR estimates.
    """
    print("\n[Task2-3a/4] Generating: timing_recommendations.csv")

    if df is None:
        df = load_data()
        df = add_derived_signals(df)

    if user_segments_df is None:
        from segmentation_engine import gen_user_segments
        user_segments_df, _ = gen_user_segments(df, output_dir)

    # Merge preferred_hour + notif_open_rate onto segment assignments
    merged = user_segments_df.merge(
        df[["user_id", "preferred_hour", "notif_open_rate_30d", "activeness_score"]],
        on="user_id", how="left"
    )
    merged["time_window"] = merged["preferred_hour"].apply(_hour_to_window)

    rows = []
    combos = merged[["segment_id", "segment_name", "lifecycle_stage"]].drop_duplicates()

    for _, combo in combos.iterrows():
        sid   = combo["segment_id"]
        sname = combo["segment_name"]
        stage = combo["lifecycle_stage"]

        sub = merged[(merged["segment_id"] == sid) & (merged["lifecycle_stage"] == stage)]
        if len(sub) == 0:
            continue

        # Score each window by avg notif_open_rate of users who prefer it
        window_scores = (
            sub.groupby("time_window")["notif_open_rate_30d"]
            .mean()
            .sort_values(ascending=False)
        )

        best_windows = window_scores.index.tolist()[:3]
        avg_open     = round(sub["notif_open_rate_30d"].mean(), 3)
        avg_active   = round(sub["activeness_score"].mean(), 3)
        notifs_day   = _get_notifs_per_day(avg_active)

        # Ask LLM for brief reasoning on timing
        raw = llm(
            system="You are a notification timing expert. Output ONLY valid JSON.",
            prompt=f"""
KNOWLEDGE BANK (use Success Metrics and User Journey stages for context):
{load_kb()}

Segment : {sname} (id: {sid})
Lifecycle: {stage}
Top preferred windows (ranked by user preference + open rate): {best_windows}
Avg notification open rate: {avg_open}
Avg activeness score: {avg_active}
Recommended notifications/day: {notifs_day}

Time windows available: {[w['name'] for w in TIME_WINDOWS]}

Return ONLY valid JSON:
{{
  "optimal_window_1": "<best window>",
  "optimal_window_2": "<second best>",
  "optimal_window_3": "<third best>",
  "timing_rationale": "<1-2 sentences: why these windows work for this segment>",
  "expected_ctr_lift": "<e.g. +3% vs random>",
  "avoid_windows":    ["<window to avoid>"]
}}"""
        )
        timing = safe_parse_json(raw, fallback={
            "optimal_window_1":  best_windows[0] if len(best_windows) > 0 else "evening",
            "optimal_window_2":  best_windows[1] if len(best_windows) > 1 else "early_morning",
            "optimal_window_3":  best_windows[2] if len(best_windows) > 2 else "night",
            "timing_rationale":  f"Based on {avg_open:.1%} avg open rate across {len(sub)} users.",
            "expected_ctr_lift": "+2%",
            "avoid_windows":     [],
        })

        rows.append({
            "segment_id":        sid,
            "segment_name":      sname,
            "lifecycle_stage":   stage,
            "user_count":        len(sub),
            "avg_notif_open_rate": avg_open,
            "avg_activeness":    avg_active,
            "notifs_per_day":    notifs_day,
            "optimal_window_1":  timing.get("optimal_window_1", "evening"),
            "optimal_window_2":  timing.get("optimal_window_2", "early_morning"),
            "optimal_window_3":  timing.get("optimal_window_3", "night"),
            "timing_rationale":  timing.get("timing_rationale", ""),
            "expected_ctr_lift": timing.get("expected_ctr_lift", "+2%"),
            "avoid_windows":     "|".join(timing.get("avoid_windows", [])) if isinstance(timing.get("avoid_windows"), list) else "",
        })

    timing_df = pd.DataFrame(rows)
    save_csv(timing_df, "timing_recommendations.csv", output_dir)
    return timing_df


def gen_user_notification_schedule(
    user_segments_df:  pd.DataFrame = None,
    templates_df:      pd.DataFrame = None,
    timing_df:         pd.DataFrame = None,
    df:                pd.DataFrame = None,
    output_dir: str = None,
) -> pd.DataFrame:
    """
    Build user_notification_schedule.csv.
    One row per user with notif_1 … notif_9 (template_id, time, channel).
    """
    print("\n[Task2-4/4] Generating: user_notification_schedule.csv")

    if df is None:
        df = load_data()
        df = add_derived_signals(df)

    if user_segments_df is None:
        from segmentation_engine import gen_user_segments
        user_segments_df, _ = gen_user_segments(df, output_dir)

    if timing_df is None:
        timing_df = gen_timing_recommendations(user_segments_df, df, output_dir)

    # Build a template pool per segment × stage (template_ids only)
    template_pool_map = {}
    if templates_df is not None and "template_id" in templates_df.columns:
        for (sid, stage), grp in templates_df.groupby(["segment_id", "lifecycle_stage"]):
            template_pool_map[(sid, stage)] = grp["template_id"].tolist()

    # Merge user data
    user_full = user_segments_df.merge(
        df[["user_id", "preferred_hour", "activeness_score", "lifecycle_stage"]],
        on=["user_id", "lifecycle_stage"], how="left"
    )

    all_rows = []
    for _, user in user_full.iterrows():
        sid   = user["segment_id"]
        stage = user["lifecycle_stage"]

        pool = template_pool_map.get((sid, stage), [f"{sid}_{stage}_fallback"])

        # Optimal windows from timing recommendations
        timing_row = timing_df[
            (timing_df["segment_id"] == sid) &
            (timing_df["lifecycle_stage"] == stage)
        ]
        seg_windows = (
            [timing_row.iloc[0]["optimal_window_1"],
             timing_row.iloc[0]["optimal_window_2"],
             timing_row.iloc[0]["optimal_window_3"]]
            if len(timing_row) > 0 else ["evening", "early_morning", "night"]
        )

        slots = _build_schedule_for_user(user, pool, seg_windows)

        row = {
            "user_id":         user["user_id"],
            "segment_id":      sid,
            "segment_name":    user.get("segment_name", ""),
            "lifecycle_stage": stage,
            "lifecycle_day":   int(user.get("days_since_signup", 0)),
            "notifs_per_day":  len(slots),
        }
        for slot in slots:
            col_prefix = slot["notif_slot"]
            row[f"{col_prefix}_template_id"] = slot["template_id"]
            row[f"{col_prefix}_time_window"] = slot["time_window"]
            row[f"{col_prefix}_channel"]     = slot["channel"]

        all_rows.append(row)

    schedule_df = pd.DataFrame(all_rows)
    save_csv(schedule_df, "user_notification_schedule.csv", output_dir)
    return schedule_df
