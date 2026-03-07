# segmentation_engine.py
# ─────────────────────────────────────────────────────────────
# Generates: user_segments.csv
#
# MECE segmentation approach:
#   1. Compute derived signals (activeness, churn risk, propensities)
#   2. Apply rule-based MECE logic to assign each user to exactly
#      one segment (no overlap, full coverage)
#   3. Use LLM to generate rich segment descriptions + strategy
#   4. Merge descriptions back onto per-user CSV
# ─────────────────────────────────────────────────────────────

import pandas as pd
from llm import llm, safe_parse_json, save_csv
from data_loader import load_data, add_derived_signals, build_data_summary
from kb_loader   import build_context
from config import OCTOLYSIS_DRIVES


# ── Segment definitions (MECE rules) ─────────────────────────
# Priority order matters — first matching rule wins.
# Together they cover every possible user row.

SEGMENT_RULES = [
    {
        "segment_id":   "SEG_01",
        "name":         "Power Learners",
        "description":  "Highly active paid users, strong streak, AI tutor engaged",
        "rule":         lambda r: (
            r["lifecycle_stage"] == "paid" and
            r["activeness_score"] >= 0.7 and
            r["feature_ai_tutor_used"]
        ),
    },
    {
        "segment_id":   "SEG_02",
        "name":         "Streak Guardians",
        "description":  "Active paid users with long streaks and gamification focus",
        "rule":         lambda r: (
            r["lifecycle_stage"] == "paid" and
            r["activeness_score"] >= 0.5 and
            r["streak_current"] >= 7
        ),
    },
    {
        "segment_id":   "SEG_03",
        "name":         "Social Climbers",
        "description":  "Leaderboard-engaged users who respond to competition",
        "rule":         lambda r: (
            r["lifecycle_stage"] in ["paid", "trial"] and
            r["feature_leaderboard_viewed"] and
            r["propensity_social"] >= 0.5
        ),
    },
    {
        "segment_id":   "SEG_04",
        "name":         "Trial Activators",
        "description":  "Trial users with high motivation who haven't converted yet",
        "rule":         lambda r: (
            r["lifecycle_stage"] == "trial" and
            r["motivation_score"] >= 0.5
        ),
    },
    {
        "segment_id":   "SEG_05",
        "name":         "Trial Fence-Sitters",
        "description":  "Trial users with low activity — at risk of not converting",
        "rule":         lambda r: (
            r["lifecycle_stage"] == "trial" and
            r["activeness_score"] < 0.5
        ),
    },
    {
        "segment_id":   "SEG_06",
        "name":         "Casual Paid Users",
        "description":  "Paid users with moderate activity — habit not yet formed",
        "rule":         lambda r: (
            r["lifecycle_stage"] == "paid" and
            r["activeness_score"] >= 0.3 and
            r["activeness_score"] < 0.7
        ),
    },
    {
        "segment_id":   "SEG_07",
        "name":         "At-Risk Paid",
        "description":  "Paid users with very low activity — high churn risk",
        "rule":         lambda r: (
            r["lifecycle_stage"] == "paid" and
            r["activeness_score"] < 0.3
        ),
    },
    {
        "segment_id":   "SEG_08",
        "name":         "Recent Churned",
        "description":  "Churned users still within winback window (< 45 days)",
        "rule":         lambda r: (
            r["lifecycle_stage"] == "churned" and
            r["days_since_signup"] < 45
        ),
    },
    {
        "segment_id":   "SEG_09",
        "name":         "Deep Churned",
        "description":  "Long-gone churned users requiring strong re-engagement",
        "rule":         lambda r: (
            r["lifecycle_stage"] == "churned" and
            r["days_since_signup"] >= 45
        ),
    },
    {
        "segment_id":   "SEG_10",
        "name":         "Inactive Sleepers",
        "description":  "Inactive users — not using app but not explicitly churned",
        "rule":         lambda r: r["lifecycle_stage"] == "inactive",
    },
    # Catch-all — ensures MECE completeness
    {
        "segment_id":   "SEG_11",
        "name":         "Unclassified",
        "description":  "Users not matching any primary segment",
        "rule":         lambda r: True,
    },
]


def _assign_segment(row: pd.Series) -> tuple[str, str]:
    """Return (segment_id, segment_name) for a single user row."""
    for seg in SEGMENT_RULES:
        try:
            if seg["rule"](row):
                return seg["segment_id"], seg["name"]
        except Exception:
            continue
    return "SEG_11", "Unclassified"


def _gen_segment_metadata(df_seg: pd.DataFrame, seg_def: dict, data_summary: str) -> dict:
    """One LLM call to produce rich metadata for a segment."""
    n      = len(df_seg)
    stages = df_seg["lifecycle_stage"].value_counts().to_dict()
    avg_act = round(df_seg["activeness_score"].mean(), 3)
    avg_churn = round(df_seg["churn_risk_score"].mean(), 3)
    avg_motiv = round(df_seg["motivation_score"].mean(), 3)

    drives_list = ", ".join(d["name"] for d in OCTOLYSIS_DRIVES)

    raw = llm(
        system="You are a product segmentation expert. Output ONLY valid JSON.",
        prompt=f"""
Segment: {seg_def['name']} (id: {seg_def['segment_id']})
Description: {seg_def['description']}
Users in segment: {n}
Lifecycle stages: {stages}
Avg activeness_score: {avg_act}
Avg churn_risk_score: {avg_churn}
Avg motivation_score: {avg_motiv}

Octolysis drives available: {drives_list}

{data_summary}

Generate metadata for this segment. Return ONLY valid JSON:
{{
  "primary_octolysis_drive": "<most relevant drive name>",
  "secondary_octolysis_drive": "<second most relevant>",
  "key_behaviour_signal": "<1 sentence: what makes this segment distinct in the data>",
  "recommended_tone": "<1-2 word tone>",
  "communication_strategy": "<2-3 sentence strategy for this segment>",
  "north_star_lever": "<how this segment contributes to north star metric>"
}}"""
    )
    return safe_parse_json(raw, fallback={
        "primary_octolysis_drive":   "Accomplishment",
        "secondary_octolysis_drive": "Loss Avoidance",
        "key_behaviour_signal":      seg_def["description"],
        "recommended_tone":          "motivating",
        "communication_strategy":    f"Focus on {seg_def['description'].lower()} to drive engagement.",
        "north_star_lever":          "Increase exercises completed per week",
    })


def gen_user_segments(df=None, output_dir: str = None) -> pd.DataFrame:
    """
    Assign all users to MECE segments and output user_segments.csv.

    Args:
        df          : pre-loaded DataFrame (optional)
        output_dir  : override output directory (optional)
    """
    print("\n[4/5] Generating: user_segments.csv")

    if df is None:
        df = load_data()

    df = add_derived_signals(df)
    # Build context = KB (target audience, journey stages, features) + data summary
    # KB's "Target Audience profiles" directly informs segment descriptions and strategy
    data_summary = build_context(build_data_summary(df))

    # Assign segment to each user
    print("  [rule] Applying MECE segment rules ...")
    segments = df.apply(_assign_segment, axis=1, result_type="expand")
    segments.columns = ["segment_id", "segment_name"]
    df = pd.concat([df, segments], axis=1)

    seg_counts = df["segment_id"].value_counts().to_dict()
    print(f"  [rule] Segment distribution: {seg_counts}")

    # Build per-segment metadata via LLM
    seg_meta_rows = []
    unique_segs   = df[["segment_id", "segment_name"]].drop_duplicates().sort_values("segment_id")

    for _, row in unique_segs.iterrows():
        sid  = row["segment_id"]
        name = row["segment_name"]
        seg_def = next((s for s in SEGMENT_RULES if s["segment_id"] == sid), {
            "segment_id": sid, "name": name, "description": name
        })
        df_seg = df[df["segment_id"] == sid]
        print(f"  [llm] Generating metadata for {sid}: {name} (n={len(df_seg)})")
        meta = _gen_segment_metadata(df_seg, seg_def, data_summary)

        seg_meta_rows.append({
            "segment_id":               sid,
            "segment_name":             name,
            "user_count":               len(df_seg),
            "lifecycle_stages":         "|".join(sorted(df_seg["lifecycle_stage"].unique())),
            "avg_activeness_score":     round(df_seg["activeness_score"].mean(), 3),
            "avg_churn_risk_score":     round(df_seg["churn_risk_score"].mean(), 3),
            "avg_propensity_gamif":     round(df_seg["propensity_gamification"].mean(), 3),
            "avg_propensity_ai_tutor":  round(df_seg["propensity_ai_tutor"].mean(), 3),
            "avg_propensity_social":    round(df_seg["propensity_social"].mean(), 3),
            "primary_octolysis_drive":  meta.get("primary_octolysis_drive", "Accomplishment"),
            "secondary_octolysis_drive":meta.get("secondary_octolysis_drive", "Loss Avoidance"),
            "key_behaviour_signal":     meta.get("key_behaviour_signal", ""),
            "recommended_tone":         meta.get("recommended_tone", "motivating"),
            "communication_strategy":   meta.get("communication_strategy", ""),
            "north_star_lever":         meta.get("north_star_lever", ""),
        })

    seg_summary_df = pd.DataFrame(seg_meta_rows)

    # Merge segment columns onto full user DataFrame
    user_seg_df = df[[
        "user_id", "lifecycle_stage", "days_since_signup", "age_band", "region",
        "activeness_score", "churn_risk_score",
        "propensity_gamification", "propensity_ai_tutor", "propensity_social",
        "segment_id", "segment_name",
    ]].copy()

    # Add communication metadata per user from segment summary
    user_seg_df = user_seg_df.merge(
        seg_summary_df[[
            "segment_id", "primary_octolysis_drive", "secondary_octolysis_drive",
            "recommended_tone", "communication_strategy",
        ]],
        on="segment_id", how="left"
    )

    save_csv(user_seg_df, "user_segments.csv", output_dir)

    # Also return the segment summary df for downstream use
    return user_seg_df, seg_summary_df
