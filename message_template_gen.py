# message_template_gen.py
# ─────────────────────────────────────────────────────────────
# Generates: message_templates.csv
#
# Creates exactly 5 templates per Segment × Lifecycle × Goal × Theme
# combination. Each template has bilingual content (Hindi + English),
# a tone, an Octolysis hook, and a feature reference.
# ─────────────────────────────────────────────────────────────

import pandas as pd
from llm import llm, safe_parse_json, save_csv
from data_loader import load_data, add_derived_signals
from kb_loader   import load_kb
from config import OCTOLYSIS_DRIVES

TEMPLATES_PER_COMBO = 5


def _drives_reference() -> str:
    return "\n".join(
        f'  {d["id"]}. {d["name"]}: "{d["hook"]}"'
        for d in OCTOLYSIS_DRIVES
    )


def _gen_templates_for_combo(
    segment_id:    str,
    segment_name:  str,
    lifecycle:     str,
    primary_goal:  str,
    primary_theme: str,
    tone:          str,
    combo_index:   int,
) -> list[dict]:
    """
    One LLM call → exactly 5 message template rows for a given combination.
    """
    raw = llm(
        system="You are a multilingual notification copywriter for an EdTech app. Output ONLY valid JSON.",
        prompt=f"""
App context (from Knowledge Bank):
{load_kb()}

Segment       : {segment_name} (id: {segment_id})
Lifecycle     : {lifecycle}
Primary goal  : {primary_goal}
Primary theme : {primary_theme}
Tone          : {tone}

Octolysis 8 Core Drives reference:
{_drives_reference()}

Generate EXACTLY 5 unique notification templates for this combination.
Each template must differ in hook type, format, and approach.
Templates should show gradual journey progression (early → mid → late engagement).

Return ONLY valid JSON array (no wrapping object):
[
  {{
    "template_id": "{segment_id}_{lifecycle}_T{combo_index:03d}_1",
    "title_en":    "<notification title in English — max 8 words>",
    "body_en":     "<notification body in English — max 20 words>",
    "title_hi":    "<notification title in Hindi — max 8 words>",
    "body_hi":     "<notification body in Hindi — max 20 words>",
    "hook_type":   "<Octolysis drive name used>",
    "cta_en":      "<call-to-action in English — max 4 words>",
    "cta_hi":      "<call-to-action in Hindi — max 4 words>",
    "feature_ref": "<ai_tutor|leaderboard|progress|streak|coins|general>",
    "journey_day": "<D0|D1|D2|D3-D5|D6-D7>"
  }}
]
Generate all 5 entries in the array above."""
    )

    parsed = safe_parse_json(raw, fallback=[])

    # Unwrap if LLM wrapped in an object
    if isinstance(parsed, dict):
        for key in ["templates", "messages", "items", "data"]:
            if key in parsed and isinstance(parsed[key], list):
                parsed = parsed[key]
                break
        else:
            parsed = []

    if not isinstance(parsed, list):
        parsed = []

    rows = []
    for t_idx, t in enumerate(parsed[:TEMPLATES_PER_COMBO], 1):
        if not isinstance(t, dict):
            continue
        rows.append({
            "template_id":   t.get("template_id", f"{segment_id}_{lifecycle}_T{combo_index:03d}_{t_idx}"),
            "segment_id":    segment_id,
            "segment_name":  segment_name,
            "lifecycle_stage": lifecycle,
            "primary_goal":  primary_goal,
            "theme":         primary_theme,
            "tone":          tone,
            "title_en":      t.get("title_en", ""),
            "body_en":       t.get("body_en", ""),
            "title_hi":      t.get("title_hi", ""),
            "body_hi":       t.get("body_hi", ""),
            "hook_type":     t.get("hook_type", primary_theme),
            "cta_en":        t.get("cta_en", "Start now"),
            "cta_hi":        t.get("cta_hi", "अभी शुरू करें"),
            "feature_ref":   t.get("feature_ref", "general"),
            "journey_day":   t.get("journey_day", "D0"),
            "iteration":     0,
        })

    # Pad to exactly TEMPLATES_PER_COMBO if LLM returned fewer
    while len(rows) < TEMPLATES_PER_COMBO:
        t_idx = len(rows) + 1
        rows.append({
            "template_id":     f"{segment_id}_{lifecycle}_T{combo_index:03d}_{t_idx}",
            "segment_id":      segment_id,
            "segment_name":    segment_name,
            "lifecycle_stage": lifecycle,
            "primary_goal":    primary_goal,
            "theme":           primary_theme,
            "tone":            tone,
            "title_en":        f"Keep learning, {segment_name}!",
            "body_en":         "Your English journey continues. Practice today and build your streak.",
            "title_hi":        "सीखते रहो!",
            "body_hi":         "आपकी अंग्रेजी यात्रा जारी है। आज अभ्यास करें।",
            "hook_type":       primary_theme,
            "cta_en":          "Practice Now",
            "cta_hi":          "अभ्यास करें",
            "feature_ref":     "general",
            "journey_day":     "D0",
            "iteration":       0,
        })

    return rows


def gen_message_templates(
    themes_df:        pd.DataFrame = None,
    goals_df:         pd.DataFrame = None,
    user_segments_df: pd.DataFrame = None,
    df:               pd.DataFrame = None,
    output_dir: str = None,
) -> pd.DataFrame:
    """
    Build message_templates.csv — 5 templates per Segment × Lifecycle × Theme.

    Args:
        themes_df        : output of gen_communication_themes (optional)
        goals_df         : output of gen_segment_goals (optional)
        user_segments_df : output of gen_user_segments (optional)
        df               : raw behavioral DataFrame (optional)
        output_dir       : override output directory (optional)
    """
    print("\n[Task2-2/4] Generating: message_templates.csv")

    if df is None:
        df = load_data()

    # Ensure themes are available
    if themes_df is None:
        from comm_themes import gen_communication_themes
        themes_df = gen_communication_themes(user_segments_df, None, df, output_dir)

    # Merge in primary_goal from goals_df if available
    if goals_df is not None:
        goal_lookup = goals_df[["segment_id", "lifecycle_stage", "primary_goal"]].drop_duplicates()
        themes_df = themes_df.merge(goal_lookup, on=["segment_id", "lifecycle_stage"], how="left")
    else:
        themes_df["primary_goal"] = "Drive daily practice"

    themes_df["primary_goal"] = themes_df["primary_goal"].fillna("Drive daily practice")

    all_rows = []
    total    = len(themes_df)

    for combo_idx, (_, row) in enumerate(themes_df.iterrows(), 1):
        sid    = row["segment_id"]
        sname  = row["segment_name"]
        stage  = row["lifecycle_stage"]
        goal   = row["primary_goal"]
        theme  = row["primary_theme"]
        tone   = row["tone"]

        print(f"  [{combo_idx}/{total}] {sid} × {stage} × {theme} → 5 templates")

        templates = _gen_templates_for_combo(sid, sname, stage, goal, theme, tone, combo_idx)
        all_rows.extend(templates)

    templates_df = pd.DataFrame(all_rows)
    save_csv(templates_df, "message_templates.csv", output_dir)
    return templates_df
