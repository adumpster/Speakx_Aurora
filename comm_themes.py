# comm_themes.py
# ─────────────────────────────────────────────────────────────
# Generates: communication_themes.csv
#
# For each segment × lifecycle stage combination:
#   - Pick primary + secondary Octolysis themes
#   - Define tone preferences and message hooks
#   - One LLM call per combination
# ─────────────────────────────────────────────────────────────

import pandas as pd
from llm import llm, safe_parse_json, save_csv
from data_loader import load_data, add_derived_signals
from kb_loader   import load_kb
from config import OCTOLYSIS_DRIVES, LIFECYCLE_STAGES


def _gen_theme_entry(
    segment_id:      str,
    segment_name:    str,
    lifecycle_stage: str,
    primary_drive:   str,
    tone_preference: str,
    stats:           dict,
) -> dict:
    """One LLM call → one row for communication_themes.csv."""

    drives_block = "\n".join(
        f'  {d["id"]}. {d["name"]}: example hook — "{d["hook"]}"'
        for d in OCTOLYSIS_DRIVES
    )

    raw = llm(
        system="You are a behavioural communication strategist. Output ONLY valid JSON.",
        prompt=f"""
KNOWLEDGE BANK (contains Ethical Communication Guidelines, product features, audience profiles):
{load_kb()}

Segment : {segment_name} (id: {segment_id})
Lifecycle stage : {lifecycle_stage}
Known primary drive : {primary_drive}
Suggested tone : {tone_preference}

Segment behavioral stats:
  avg_activeness    : {stats.get('avg_activeness', 0.5)}
  avg_churn_risk    : {stats.get('avg_churn_risk', 0.3)}
  avg_motivation    : {stats.get('avg_motivation', 0.5)}
  avg_notif_open    : {stats.get('avg_notif_open', 0.3)}

Octolysis 8 Core Drives reference:
{drives_block}

Select the best communication theme for this segment × stage.
Use the KB's Ethical Communication Guidelines for allowed tones.
Provide a primary drive, secondary drive, hooks in both English and Hindi,
and a tone rationale grounded in the KB guidelines and behavioral stats.

Return ONLY valid JSON:
{{
  "primary_theme":         "<Octolysis drive name>",
  "secondary_theme":       "<Octolysis drive name>",
  "tone":                  "<1-2 word tone descriptor>",
  "hook_en":               "<English hook message — max 15 words>",
  "hook_hi":               "<Hindi hook message — max 15 words>",
  "theme_rationale":       "<1-2 sentences: why this theme fits this segment + stage>",
  "avoid_themes":          ["<drive name to avoid>"],
  "preferred_channel":     "push_notification",
  "message_length":        "<short|medium|long>"
}}"""
    )

    result = safe_parse_json(raw, fallback={
        "primary_theme":     primary_drive,
        "secondary_theme":   "Loss Avoidance",
        "tone":              tone_preference,
        "hook_en":           "Keep going! Your progress is amazing.",
        "hook_hi":           "बढ़ते रहो! आपकी प्रगति शानदार है।",
        "theme_rationale":   f"Theme chosen based on {segment_name} behavioral profile.",
        "avoid_themes":      ["aggressive"],
        "preferred_channel": "push_notification",
        "message_length":    "medium",
    })

    return {
        "segment_id":        segment_id,
        "segment_name":      segment_name,
        "lifecycle_stage":   lifecycle_stage,
        "primary_theme":     result.get("primary_theme", primary_drive),
        "secondary_theme":   result.get("secondary_theme", "Loss Avoidance"),
        "tone":              result.get("tone", tone_preference),
        "hook_en":           result.get("hook_en", ""),
        "hook_hi":           result.get("hook_hi", ""),
        "theme_rationale":   result.get("theme_rationale", ""),
        "avoid_themes":      "|".join(result.get("avoid_themes", [])) if isinstance(result.get("avoid_themes"), list) else str(result.get("avoid_themes", "")),
        "preferred_channel": result.get("preferred_channel", "push_notification"),
        "message_length":    result.get("message_length", "medium"),
    }


def gen_communication_themes(
    user_segments_df: pd.DataFrame = None,
    seg_summary_df:   pd.DataFrame = None,
    df:               pd.DataFrame = None,
    output_dir: str = None,
) -> pd.DataFrame:
    """
    Build communication_themes.csv.

    Args:
        user_segments_df : output from gen_user_segments (optional)
        seg_summary_df   : segment-level summary with propensities (optional)
        df               : raw behavioral DataFrame (optional)
        output_dir       : override output directory (optional)
    """
    print("\n[Task2-1/4] Generating: communication_themes.csv")

    if df is None:
        df = load_data()
        df = add_derived_signals(df)

    # If we have user segments, use them; otherwise run segmentation inline
    if user_segments_df is None or "segment_id" not in user_segments_df.columns:
        from segmentation_engine import gen_user_segments
        user_segments_df, seg_summary_df = gen_user_segments(df, output_dir)

    combos = (
        user_segments_df[["segment_id", "segment_name", "lifecycle_stage",
                           "primary_octolysis_drive", "recommended_tone"]]
        .drop_duplicates(subset=["segment_id", "lifecycle_stage"])
        .sort_values(["segment_id", "lifecycle_stage"])
    )

    rows = []
    total = len(combos)
    for i, (_, combo) in enumerate(combos.iterrows()):
        sid    = combo["segment_id"]
        sname  = combo["segment_name"]
        stage  = combo["lifecycle_stage"]
        drive  = combo.get("primary_octolysis_drive", "Accomplishment")
        tone   = combo.get("recommended_tone", "motivating")

        # Compute stats for this segment
        seg_users = user_segments_df[user_segments_df["segment_id"] == sid]["user_id"]
        seg_df    = df[df["user_id"].isin(seg_users)]

        stats = {
            "avg_activeness": round(seg_df["activeness_score"].mean(), 3) if "activeness_score" in seg_df.columns else 0.5,
            "avg_churn_risk": round(seg_df["churn_risk_score"].mean(), 3) if "churn_risk_score" in seg_df.columns else 0.3,
            "avg_motivation": round(seg_df["motivation_score"].mean(), 3),
            "avg_notif_open": round(seg_df["notif_open_rate_30d"].mean(), 3),
        }

        print(f"  [{i+1}/{total}] {sid} × {stage}")
        row = _gen_theme_entry(sid, sname, stage, drive, tone, stats)
        rows.append(row)

    themes_df = pd.DataFrame(rows)
    save_csv(themes_df, "communication_themes.csv", output_dir)
    return themes_df
