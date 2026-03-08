import pandas as pd
import numpy as np
import os


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
        # Captures 21-23 and late night 0-5
        return "night"


def generate_dynamic_timing_recommendations():
    # Setup paths pointing to the iteration 0 folder
    script_dir = os.path.dirname(os.path.abspath(__file__))
    iteration_0_dir = os.path.normpath(os.path.join(
        script_dir, "..", "iteration_0_before_learning"))
    segments_path = os.path.join(iteration_0_dir, "user_segments.csv")

    # 1. Load the dynamically generated user segments
    try:
        df = pd.read_csv(segments_path)
    except FileNotFoundError:
        print(
            f"Error: Could not find {segments_path}. Run segmentation first.")
        return

    # 2. Map every user's preferred hour to a standard window
    df['time_window'] = df['preferred_hour'].apply(map_hour_to_window)

    timing_data = []

    # 3. Analyze preferences dynamically per segment
    grouped = df.groupby(['segment_id', 'segment_name'])

    for (seg_id, seg_name), group in grouped:
        # Determine how many windows this segment needs based on daily frequency limits
        avg_freq = group['daily_frequency'].mean()
        if avg_freq >= 7:
            num_windows = 4
        elif avg_freq >= 5:
            num_windows = 3
        else:
            num_windows = 2

        # Get the top N most popular time windows for THIS specific segment in THIS dataset
        window_counts = group['time_window'].value_counts()
        top_windows = window_counts.nlargest(num_windows).index.tolist()

        # Fallback: Just in case a segment is so tiny it doesn't have enough unique preferred hours
        if len(top_windows) < num_windows:
            all_windows = ["early_morning", "mid_morning",
                           "afternoon", "late_afternoon", "evening", "night"]
            for w in all_windows:
                if w not in top_windows:
                    top_windows.append(w)
                if len(top_windows) == num_windows:
                    break

        # Calculate dynamic baseline metrics based on the segment's actual average activeness
        avg_activeness = group['activeness_score'].mean()

        # Base CTR floats around 4-14% (Neutral/Bad band), scaled by activeness
        base_ctr = max(0.04, min(0.14, avg_activeness * 0.18))
        # Base Engagement floats around 12-39% (Neutral/Bad band), scaled by activeness
        base_eng = max(0.12, min(0.39, avg_activeness * 0.45))

        for rank, window in enumerate(top_windows):
            # Slightly decay expected metrics for their 2nd, 3rd, and 4th most preferred windows
            decay_factor = 1.0 - (rank * 0.1)

            timing_data.append({
                "segment_id": seg_id,
                "segment_name": seg_name,
                "recommended_time_window": window,
                "expected_ctr": round(base_ctr * decay_factor, 3),
                "expected_engagement": round(base_eng * decay_factor, 3),
                "rationale": f"Rank {rank+1} preferred window based on behavioral data."
            })

    # 4. Export the dynamic recommendations
    out_df = pd.DataFrame(timing_data)
    file_path = os.path.join(iteration_0_dir, "timing_recommendations.csv")
    out_df.to_csv(file_path, index=False)

    print(f"✅ Successfully generated {file_path} dynamically!")
    print(
        f"Mapped {len(out_df)} data-driven window recommendations based on preferred_hour.")


if __name__ == "__main__":
    generate_dynamic_timing_recommendations()
