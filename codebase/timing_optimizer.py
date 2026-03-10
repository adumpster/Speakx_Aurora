# timing_optimizer.py
# ─────────────────────────────────────────────────────────────
# Generates:
#   timing_recommendations.csv      — segment-level time windows
#   user_notification_schedule.csv  — per-user schedule (user × window × template)
# ─────────────────────────────────────────────────────────────

import pandas as pd
import numpy as np
from llm import save_csv


def map_hour_to_window(hour):
    """Maps an integer hour (0-23) to the 6 standard time windows."""
    if pd.isna(hour):
        return "evening"  # Safe fallback for missing data

    hour = int(hour)
    if 6 <= hour < 9:
        return "early_morning"
    elif 9 <= hour < 12:
        return "mid_morning"
    elif 12 <= hour < 15:
        return "afternoon"
    elif 15 <= hour < 18:
        return "late_afternoon"
    elif 18 <= hour < 21:
        return "evening"
    else:
        return "night"


def gen_timing_recommendations(user_seg_df: pd.DataFrame, raw_df: pd.DataFrame, output_dir: str = None) -> pd.DataFrame:
    """
    Generates segment-level timing recommendations based on users' preferred hours.

    Args:
        user_seg_df : user_segments.csv DataFrame (has segment_id, segment_name,
                      activeness_band, activeness_score)
        raw_df      : cleaned behavioral DataFrame from data_loader (has preferred_hour)
        output_dir  : output folder (defaults to config.OUTPUT_DIR_0)

    Returns:
        DataFrame saved as timing_recommendations.csv
    """
    print("\n[timing] Generating timing_recommendations.csv ...")

    # Merge user segments with preferred_hour from raw behavioral data
    df = pd.merge(
        user_seg_df,
        raw_df[['user_id', 'preferred_hour']],
        on='user_id',
        how='left'
    )

    # Map every user's preferred hour to a standard window
    df['time_window'] = df['preferred_hour'].apply(map_hour_to_window)

    timing_data = []

    # Analyze preferences dynamically per segment
    grouped = df.groupby(['segment_id', 'segment_name', 'activeness_band'])

    for (seg_id, seg_name, act_band), group in grouped:

        # Determine notification volume based on Activeness Band
        if act_band == "high":
            num_windows = 3
            urgency = "High frequency for habit reinforcement & streaks."
        elif act_band == "moderate":
            num_windows = 2
            urgency = "Medium frequency to lower friction and build habit."
        else:
            # Low, Churned, or Inactive -> DO NOT SPAM.
            num_windows = 1
            urgency = "Low frequency (1 window). High-impact win-back only to prevent uninstalls."

        # Get the top N most popular time windows for this specific segment
        window_counts = group['time_window'].value_counts()
        top_windows = window_counts.nlargest(num_windows).index.tolist()

        # Fallback if a segment doesn't have enough data
        if len(top_windows) < num_windows:
            all_windows = ["early_morning", "evening", "afternoon",
                           "mid_morning", "late_afternoon", "night"]
            for w in all_windows:
                if w not in top_windows:
                    top_windows.append(w)
                if len(top_windows) == num_windows:
                    break

        # Calculate dynamic baseline metrics based on the segment's actual average activeness
        avg_activeness = group['activeness_score'].mean()
        if pd.isna(avg_activeness):
            avg_activeness = 0.1  # Default low for safety

        # Adjust expected metrics to reflect reality (churned users will have terrible CTRs)
        base_ctr = max(0.01, min(0.20, avg_activeness * 0.25))
        base_eng = max(0.05, min(0.50, avg_activeness * 0.55))

        for rank, window in enumerate(top_windows):
            # Decay expected metrics for 2nd/3rd notifications in a day
            decay_factor = 1.0 - (rank * 0.15)

            timing_data.append({
                "segment_id": seg_id,
                "segment_name": seg_name,
                "recommended_time_window": window,
                "expected_ctr": round(base_ctr * decay_factor, 3),
                "expected_engagement": round(base_eng * decay_factor, 3),
                "rationale": f"Rank {rank+1} preferred historical window. Strategy: {urgency}"
            })

    out_df = pd.DataFrame(timing_data)
    out_df = out_df.sort_values(
        by=['segment_id', 'expected_ctr'], ascending=[True, False]
    ).reset_index(drop=True)

    save_csv(out_df, "timing_recommendations.csv", output_dir)

    print(f"  [timing] {len(out_df)} window recommendations across {len(grouped)} segments")
    return out_df


def gen_user_notification_schedule(
    user_seg_df: pd.DataFrame,
    templates_df: pd.DataFrame,
    timing_df: pd.DataFrame,
    _raw_df: pd.DataFrame,
    output_dir: str = None,
) -> pd.DataFrame:
    """
    Generates a per-user notification schedule by assigning each user their
    segment's recommended time windows and a matching message template.

    Args:
        user_seg_df  : user_segments.csv DataFrame
        templates_df : message_templates.csv DataFrame
        timing_df    : timing_recommendations.csv DataFrame
        _raw_df      : behavioral DataFrame (passed by main.py pipeline, reserved for future use)
        output_dir   : output folder (defaults to config.OUTPUT_DIR_0)

    Returns:
        DataFrame saved as user_notification_schedule.csv
    """
    print("\n[timing] Generating user_notification_schedule.csv ...")

    schedule_rows = []

    for _, user in user_seg_df.iterrows():
        uid = user['user_id']
        seg_id = user['segment_id']
        seg_name = user.get('segment_name', '')

        # Get timing windows for this segment
        seg_timing = timing_df[timing_df['segment_id'] == seg_id].sort_values(
            'expected_ctr', ascending=False
        )

        if seg_timing.empty:
            # Fallback: single evening window
            windows = [{"recommended_time_window": "evening", "expected_ctr": 0.05,
                        "expected_engagement": 0.10}]
        else:
            windows = seg_timing.to_dict('records')

        # Get templates for this segment (if templates_df has segment_id column)
        if templates_df is not None and 'segment_id' in templates_df.columns:
            seg_templates = templates_df[templates_df['segment_id'] == seg_id]
        else:
            seg_templates = pd.DataFrame()

        for rank, window_row in enumerate(windows):
            time_window = window_row['recommended_time_window']

            # Pick a template for this window slot (cycle through available templates)
            if not seg_templates.empty:
                tmpl = seg_templates.iloc[rank % len(seg_templates)]
                template_id = tmpl.get('template_id', tmpl.get('id', f"{seg_id}_T{rank+1}"))
                message_title = tmpl.get('title', tmpl.get('message_title', ''))
                message_body  = tmpl.get('body',  tmpl.get('message_body', ''))
            else:
                template_id   = f"{seg_id}_T{rank+1}"
                message_title = ""
                message_body  = ""

            schedule_rows.append({
                "user_id":              uid,
                "segment_id":           seg_id,
                "segment_name":         seg_name,
                "notification_rank":    rank + 1,
                "time_window":          time_window,
                "template_id":          template_id,
                "message_title":        message_title,
                "message_body":         message_body,
                "expected_ctr":         window_row.get('expected_ctr', 0.05),
                "expected_engagement":  window_row.get('expected_engagement', 0.10),
            })

    schedule_df = pd.DataFrame(schedule_rows)
    schedule_df = schedule_df.sort_values(['segment_id', 'user_id', 'notification_rank']).reset_index(drop=True)

    save_csv(schedule_df, "user_notification_schedule.csv", output_dir)

    print(f"  [timing] {len(schedule_df)} schedule entries for {schedule_df['user_id'].nunique()} users")
    return schedule_df
