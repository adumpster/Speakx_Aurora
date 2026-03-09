import pandas as pd
import numpy as np
import os
from data_loader import load_data  # Leverage his existing data loader!


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


def generate_dynamic_timing_recommendations():
    # Setup paths matching the new teammate repo structure
    script_dir = os.path.dirname(os.path.abspath(__file__))
    iteration_0_dir = os.path.join(script_dir, "iteration_0_before_learning")
    segments_path = os.path.join(iteration_0_dir, "user_segments.csv")

    os.makedirs(iteration_0_dir, exist_ok=True)

    # 1. Load the dynamically generated user segments
    try:
        segments_df = pd.read_csv(segments_path)
    except FileNotFoundError:
        print(
            f"Error: Could not find {segments_path}. Run segmentation first.")
        return

    # 2. Load the raw data using HIS data_loader
    print("Loading raw data to extract preferred_hour and daily_frequency...")
    raw_df = load_data()

    # 3. Merge them together on user_id
    df = pd.merge(
        segments_df,
        raw_df[['user_id', 'preferred_hour']],
        on='user_id',
        how='left'
    )

    # 4. Map every user's preferred hour to a standard window
    df['time_window'] = df['preferred_hour'].apply(map_hour_to_window)

    timing_data = []

    # 5. Analyze preferences dynamically per segment
    grouped = df.groupby(['segment_id', 'segment_name', 'activeness_band'])

    for (seg_id, seg_name, act_band), group in grouped:

        # --- NEW LOGIC: Determine notification volume based on Activeness Band ---
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

        # Get the top N most popular time windows for THIS specific segment
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
            # Decay expected metrics for their 2nd/3rd notifications in a day
            decay_factor = 1.0 - (rank * 0.15)

            timing_data.append({
                "segment_id": seg_id,
                "segment_name": seg_name,
                "recommended_time_window": window,
                "expected_ctr": round(base_ctr * decay_factor, 3),
                "expected_engagement": round(base_eng * decay_factor, 3),
                "rationale": f"Rank {rank+1} preferred historical window. Strategy: {urgency}"
            })

    # 6. Export the dynamic recommendations
    out_df = pd.DataFrame(timing_data)
    # Sort nicely by segment ID
    out_df = out_df.sort_values(
        by=['segment_id', 'expected_ctr'], ascending=[True, False])

    file_path = os.path.join(iteration_0_dir, "timing_recommendations.csv")
    out_df.to_csv(file_path, index=False)

    print(f"✅ Successfully generated {file_path} dynamically!")
    print(
        f"Mapped {len(out_df)} strategic window recommendations across {len(grouped)} MECE segments.")


if __name__ == "__main__":
    generate_dynamic_timing_recommendations()
