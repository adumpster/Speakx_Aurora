# learning_engine.py

# ─────────────────────────────────────────────────────────────

# Task 3: Execution & Self-Learning — 5-Phase Architecture

#

# Phase 1: Data Ingestion & State Evaluation (deterministic)

# Phase 2: Timing & Frequency Resolution (deterministic)

# Phase 3: Template Evolution (hybrid: deterministic + LLM)

# Phase 4: Schedule Regeneration (deterministic)

# Phase 5: Delta Report Compilation

# ─────────────────────────────────────────────────────────────



import os

import json

import shutil

import pandas as pd

import numpy as np

from datetime import datetime



from llm import llm, safe_parse_json, save_csv

from kb_loader import load_kb

from config import (

    EXPERIMENT_RESULTS_PATH,

    TEMPLATE_THRESHOLDS,

    GUARDRAIL_UNINSTALL_RATE,

    OUTPUT_DIR_0,

    OUTPUT_DIR_1,

)





# ═════════════════════════════════════════════════════════════

# GLOBALS — variety tracking (reset each run)

# ═════════════════════════════════════════════════════════════



_used_replacement_themes = {}   # {segment_id: set(theme, ...)}

_generated_titles        = set()

_segment_angle_index     = {}   # {segment_id: int}



THEME_POOL = [

    "Loss Avoidance",

    "Curiosity",

    "Social Proof",

    "Scarcity",

    "Epic Meaning",

    "Accomplishment",

    "Empowerment",

    "Unpredictability",

    "Ownership",

]



SEGMENT_ANGLES = {

    "SEG_02": ["cooking metaphor", "sports journey", "garden growing", "music practice", "puzzle solving"],

    "SEG_03": ["rocket launch", "mountain climbing", "treasure hunt", "recipe mastery", "chess strategy"],

    "SEG_04": ["marathon training", "building a house", "video game leveling", "artist studio", "science experiment"],

    "SEG_05": ["exploring new territory", "upgrading your toolkit", "discovering hidden gems", "unlocking bonus levels", "mastering a craft"],

    "SEG_06": ["comeback story", "phoenix rising", "second wind", "hidden reserve", "plot twist"],

    "SEG_09": ["reunion story", "time capsule", "fresh chapter", "new season", "encore performance"],

    "SEG_10": ["wake-up call", "spotlight moment", "backstage pass", "surprise gift", "secret path"],

}





# ═════════════════════════════════════════════════════════════

# HELPERS — creative angles & theme rotation

# ═════════════════════════════════════════════════════════════



_EXPERIMENT_COLUMN_ALIASES = {
    "template_id": ["template_id", "template", "message_template_id"],
    "segment_id": ["segment_id", "segment", "segment_code"],
    "primary_goal": ["primary_goal", "goal"],
    "notification_window": ["notification_window", "time_window", "recommended_time_window"],
}


def _resolve_row_goal(row: pd.Series) -> str:

    """Read goal from either legacy `primary_goal` or new `goal` column."""

    goal = row.get("primary_goal", row.get("goal", ""))

    if pd.isna(goal) or str(goal).strip() == "":

        return "Drive engagement"

    return str(goal).strip()


def _normalise_experiment_results_schema(df: pd.DataFrame) -> pd.DataFrame:

    """

    Normalise experiment_results.csv into the columns this engine expects.

    Supports both legacy and new schema variants without changing downstream logic.

    """

    out = df.copy()

    out.columns = [str(c).strip() for c in out.columns]



    rename_map = {}

    for target, aliases in _EXPERIMENT_COLUMN_ALIASES.items():

        if target in out.columns:

            continue

        for alias in aliases:

            if alias in out.columns:

                rename_map[alias] = target

                break

    if rename_map:

        out = out.rename(columns=rename_map)



    # Backfill key rates from totals when needed.

    if "ctr" not in out.columns and {"total_opens", "total_sends"}.issubset(out.columns):

        sends = pd.to_numeric(out["total_sends"], errors="coerce").replace(0, np.nan)

        opens = pd.to_numeric(out["total_opens"], errors="coerce")

        out["ctr"] = (opens / sends).fillna(0.0)



    if "engagement_rate" not in out.columns and {"total_engagements", "total_sends"}.issubset(out.columns):

        sends = pd.to_numeric(out["total_sends"], errors="coerce").replace(0, np.nan)

        engagements = pd.to_numeric(out["total_engagements"], errors="coerce")

        out["engagement_rate"] = (engagements / sends).fillna(0.0)



    if "uninstall_rate" not in out.columns:

        out["uninstall_rate"] = 0.0



    for col in ["ctr", "engagement_rate", "uninstall_rate"]:

        out[col] = pd.to_numeric(out.get(col, 0.0), errors="coerce").fillna(0.0)



    if "template_id" not in out.columns:

        out["template_id"] = [f"AUTO_TPL_{i+1}" for i in range(len(out))]

        print("  [P1] Missing template_id in experiments -> generated AUTO_TPL_* ids")



    return out



def _get_creative_angle(segment_id: str) -> str:

    """Return the next creative angle for this segment, cycling through options."""

    global _segment_angle_index

    angles = SEGMENT_ANGLES.get(

        segment_id,

        ["unique perspective", "fresh take", "surprising twist", "bold claim", "emotional hook"],

    )

    if segment_id not in _segment_angle_index:

        _segment_angle_index[segment_id] = 0

    idx = _segment_angle_index[segment_id] % len(angles)

    _segment_angle_index[segment_id] = idx + 1

    return angles[idx]





def _identify_replacement_theme(

    failed_theme: str,

    segment_id: str,

    exp_df: pd.DataFrame,

) -> str:

    """

    Pick a replacement theme with FORCED VARIETY per segment.

    Cycles through full Octalysis pool, never repeating within same segment.

    """

    global _used_replacement_themes



    if segment_id not in _used_replacement_themes:

        _used_replacement_themes[segment_id] = set()

    already_used = _used_replacement_themes[segment_id]

    excluded = {failed_theme.strip().lower()} | {t.lower() for t in already_used}



    # Strategy 1: best-performing unseen theme from experiments

    seg_data = exp_df[exp_df["segment_id"] == segment_id]

    if seg_data.empty:

        def _norm(s):

            s = str(s).strip().lower()

            for p in ["seg_", "segment_"]:

                if s.startswith(p):

                    s = s[len(p):]

            return s

        exp_copy = exp_df.copy()

        exp_copy["_seg_n"] = exp_copy["segment_id"].apply(_norm)

        seg_data = exp_copy[exp_copy["_seg_n"] == _norm(segment_id)]



    if "theme" in seg_data.columns and len(seg_data) > 0:

        theme_perf = (

            seg_data.groupby("theme")["ctr"]

            .mean()

            .sort_values(ascending=False)

        )

        for theme_name in theme_perf.index:

            if theme_name.strip().lower() not in excluded:

                _used_replacement_themes[segment_id].add(theme_name)

                return theme_name



    # Strategy 2: rotate through full pool

    for theme_name in THEME_POOL:

        if theme_name.strip().lower() not in excluded:

            _used_replacement_themes[segment_id].add(theme_name)

            return theme_name



    # Strategy 3: exhausted — reset and pick first different

    _used_replacement_themes[segment_id] = set()

    for theme_name in THEME_POOL:

        if theme_name.strip().lower() != failed_theme.strip().lower():

            _used_replacement_themes[segment_id].add(theme_name)

            return theme_name



    return "Curiosity"





# ═════════════════════════════════════════════════════════════

# LLM REWRITE FUNCTIONS

# ═════════════════════════════════════════════════════════════



def _rewrite_bad_template(

    original_row: pd.Series,

    new_theme: str,

    good_refs: list[dict],

) -> dict:

    global _generated_titles



    angle = _get_creative_angle(original_row.get("segment_id", ""))



    refs_block = "\n".join(

        f'  - [{r.get("theme", "")}] "{r.get("title_en", "")}" — CTR: {r.get("ctr", "?")}'

        for r in good_refs[:3]

    )



    avoid_block = ""

    if _generated_titles:

        avoid_block = "ALREADY USED TITLES (DO NOT reuse or paraphrase):\n" + "\n".join(

            f'  ❌ "{t}"' for t in list(_generated_titles)[-12:]

        )



    raw = llm(

        system="You are an elite mobile notification copywriter. Your #1 rule: NEVER repeat a title. Each message uses a completely different metaphor. Output ONLY valid JSON.",

        prompt=f"""KNOWLEDGE BANK:

{load_kb()}



FAILED TEMPLATE (BAD — rewrite completely):

  template_id : {original_row.get('template_id', '')}

  segment     : {original_row.get('segment_id', '')} | {original_row.get('segment_name', '')} | {original_row.get('lifecycle_stage', '')}

  old_theme   : {original_row.get('theme', '')}

  old_title   : {original_row.get('title_en', '')}

  old_body    : {original_row.get('body_en', '')}

  CTR         : {original_row.get('ctr', 0):.2%}

  goal        : {_resolve_row_goal(original_row)}



NEW THEME: {new_theme}

MANDATORY CREATIVE ANGLE: Use a "{angle}" metaphor/framing.



{avoid_block}



TOP PERFORMERS (for tone reference only — do NOT copy):

{refs_block}



STRICT RULES:

1. Title MUST use the "{angle}" angle — NOT generic motivation

2. Title max 8 words. Must be COMPLETELY unique from everything above

3. Body max 20 words. Mention a SPECIFIC SpeakX feature (AI tutor, pronunciation checker, streak tracker, live practice rooms, vocabulary builder, daily challenges)

4. CTA must be action-specific (NOT "Start Now" or "Learn Now")

5. Hindi must be natural, not translated — use colloquial tone



Return ONLY valid JSON:

{{

  "title_en":  "<8 words max, {angle} angle>",

  "body_en":   "<20 words max, specific feature>",

  "title_hi":  "<8 words max, natural Hindi>",

  "body_hi":   "<20 words max, natural Hindi>",

  "hook_type": "{new_theme}",

  "cta_en":    "<4 words max, specific action>",

  "cta_hi":    "<4 words max>",

  "improvement_rationale": "<why this angle + theme works for this segment>"

}}""",

    )



    result = safe_parse_json(raw, fallback={

        "title_en": f"Your {angle.title()} Awaits — {new_theme}",

        "body_en": f"Tap into your {angle} with SpeakX's AI tutor today.",

        "title_hi": f"आपकी {angle} यात्रा शुरू होती है",

        "body_hi": "SpeakX AI ट्यूटर के साथ आज अभ्यास करें।",

        "hook_type": new_theme,

        "cta_en": "Start Practicing",

        "cta_hi": "अभ्यास शुरू करें",

        "improvement_rationale": f"Applied {new_theme} via {angle} angle for {original_row.get('segment_id', '')}",

    })



    title_en = (result.get("title_en") or "").strip()

    if title_en:

        _generated_titles.add(title_en)

    return result





def _iterate_neutral_template(

    original_row: pd.Series,

    good_refs: list[dict],

) -> dict:

    global _generated_titles



    angle = _get_creative_angle(original_row.get("segment_id", ""))

    theme = original_row.get("theme", "Empowerment")



    refs_block = "\n".join(

        f'  - [{r.get("theme", "")}] "{r.get("title_en", "")}" — CTR: {r.get("ctr", "?")}'

        for r in good_refs[:3]

    )



    avoid_block = ""

    if _generated_titles:

        avoid_block = "ALREADY USED TITLES (DO NOT reuse or paraphrase):\n" + "\n".join(

            f'  ❌ "{t}"' for t in list(_generated_titles)[-12:]

        )



    raw = llm(

        system="You are an elite mobile notification copywriter improving average-performing messages. Every title must be unique. Output ONLY valid JSON.",

        prompt=f"""KNOWLEDGE BANK:

{load_kb()}



NEUTRAL TEMPLATE (needs sharper hook):

  template_id : {original_row.get('template_id', '')}

  segment     : {original_row.get('segment_id', '')} | {original_row.get('segment_name', '')} | {original_row.get('lifecycle_stage', '')}

  theme       : {theme}

  current     : "{original_row.get('title_en', '')}" — "{original_row.get('body_en', '')}"

  CTR         : {original_row.get('ctr', 0):.2%}

  goal        : {_resolve_row_goal(original_row)}



KEEP THE SAME THEME: {theme}

MANDATORY CREATIVE ANGLE: Use a "{angle}" metaphor/framing.



{avoid_block}



TOP PERFORMERS (tone reference only):

{refs_block}



STRICT RULES:

1. KEEP theme "{theme}" — same motivational driver

2. Title MUST use "{angle}" angle — fresh metaphor

3. Title max 8 words. COMPLETELY unique

4. Body max 20 words. Reference specific feature

5. More urgent/punchy than original but NOT spammy



Return ONLY valid JSON:

{{

  "title_en":  "<8 words max, {angle} angle, {theme} theme>",

  "body_en":   "<20 words max, specific feature>",

  "title_hi":  "<8 words max, natural Hindi>",

  "body_hi":   "<20 words max, natural Hindi>",

  "hook_type": "{theme}",

  "cta_en":    "<4 words max, specific action>",

  "cta_hi":    "<4 words max>",

  "improvement_rationale": "<why this is punchier>"

}}""",

    )



    result = safe_parse_json(raw, fallback={

        "title_en": original_row.get("title_en", "Keep going!"),

        "body_en": original_row.get("body_en", "Practice makes perfect."),

        "title_hi": original_row.get("title_hi", "जारी रखें!"),

        "body_hi": original_row.get("body_hi", "अभ्यास से सिद्धि होती है।"),

        "hook_type": theme,

        "cta_en": "Continue Now",

        "cta_hi": "जारी रखें",

        "improvement_rationale": f"Sharpened with {angle} angle.",

    })



    title_en = (result.get("title_en") or "").strip()

    if title_en:

        _generated_titles.add(title_en)

    return result





# ═════════════════════════════════════════════════════════════

# PHASE 1: Data Ingestion & State Evaluation (deterministic)

# ═════════════════════════════════════════════════════════════



def load_and_classify_experiments(path: str) -> pd.DataFrame:

    """Load experiment_results.csv and classify each row as GOOD / NEUTRAL / BAD."""

    print("  [P1] Loading experiment results ...")

    df = pd.read_csv(path)

    df = _normalise_experiment_results_schema(df)

    if "segment_id" not in df.columns:

        print("  [P1] Missing segment_id in experiment results")

    if "notification_window" not in df.columns:

        print("  [P1] Missing notification_window in experiment results; timing aggregation may be skipped")

    if "primary_goal" not in df.columns and "goal" in df.columns:

        df["primary_goal"] = df["goal"]



    good = TEMPLATE_THRESHOLDS["GOOD"]

    neut = TEMPLATE_THRESHOLDS["NEUTRAL"]



    def classify(row):

        ctr = row.get("ctr", 0)

        eng = row.get("engagement_rate", 0)

        if ctr >= good["ctr_min"] and eng >= good["engagement_min"]:

            return "GOOD"

        elif ctr >= neut["ctr_min"] and eng >= neut["engagement_min"]:

            return "NEUTRAL"

        else:

            return "BAD"



    df["performance_status"] = df.apply(classify, axis=1)

    counts = df["performance_status"].value_counts().to_dict()

    print(f"  [P1] Classification: {counts}")

    return df





def evaluate_segment_guardrails(exp_df: pd.DataFrame) -> dict:

    """

    Group by segment_id, compute avg uninstall_rate.

    Flag segments where uninstall_rate > GUARDRAIL_UNINSTALL_RATE (2%).

    Returns: {segment_id: {avg_uninstall_rate, avg_ctr, avg_engagement, guardrail_breached}}

    """

    print("  [P1] Evaluating segment-level guardrails ...")



    if "segment_id" not in exp_df.columns:

        print("  [P1] Missing segment_id column — cannot evaluate guardrails")

        return {}



    df = exp_df.copy()

    if "template_id" not in df.columns:

        df["template_id"] = np.arange(len(df))

    for col in ["uninstall_rate", "ctr", "engagement_rate"]:

        if col not in df.columns:

            df[col] = 0.0



    # Weighted uninstall rate to avoid Simpson's paradox when send volumes are uneven.
    df["total_sends"] = pd.to_numeric(df.get("total_sends", 1000), errors="coerce").fillna(1000)
    df["total_uninstalls"] = df["uninstall_rate"] * df["total_sends"]
    seg_agg = df.groupby("segment_id").agg(
        total_uninstalls=("total_uninstalls", "sum"),
        total_sends=("total_sends", "sum"),
        avg_ctr=("ctr", "mean"),
        avg_engagement=("engagement_rate", "mean"),
        template_count=("template_id", "nunique"),
    ).reset_index()
    seg_agg["avg_uninstall_rate"] = (seg_agg["total_uninstalls"] / seg_agg["total_sends"]).fillna(0)



    guardrails = {}

    breached_count = 0

    for _, row in seg_agg.iterrows():

        sid = row["segment_id"]

        breached = row["avg_uninstall_rate"] > GUARDRAIL_UNINSTALL_RATE

        if breached:

            breached_count += 1

        guardrails[sid] = {

            "avg_uninstall_rate": round(row["avg_uninstall_rate"], 4),

            "avg_ctr": round(row["avg_ctr"], 4),

            "avg_engagement": round(row["avg_engagement"], 4),

            "template_count": int(row["template_count"]),

            "guardrail_breached": breached,

        }



    print(f"  [P1] {breached_count}/{len(guardrails)} segments breached uninstall guardrail (>{GUARDRAIL_UNINSTALL_RATE:.0%})")

    return guardrails





def aggregate_timing_performance(exp_df: pd.DataFrame) -> pd.DataFrame:

    """

    Group by segment_id + notification_window.

    Compute combined_score = (mean_ctr * 0.5) + (mean_engagement_rate * 0.5).

    """

    print("  [P1] Aggregating timing-level performance ...")

    if "segment_id" not in exp_df.columns or "notification_window" not in exp_df.columns:

        print("  [P1] Missing segment_id/notification_window — skipping timing aggregation")

        return pd.DataFrame()



    df = exp_df.copy()

    if "template_id" not in df.columns:

        df["template_id"] = np.arange(len(df))

    for col in ["ctr", "engagement_rate"]:

        if col not in df.columns:

            df[col] = 0.0



    timing_agg = df.groupby(["segment_id", "notification_window"]).agg(

        mean_ctr=("ctr", "mean"),

        mean_engagement=("engagement_rate", "mean"),

        sample_count=("template_id", "count"),

    ).reset_index()



    timing_agg["combined_score"] = (

        timing_agg["mean_ctr"] * 0.5 + timing_agg["mean_engagement"] * 0.5

    ).round(4)



    timing_agg = timing_agg.sort_values(

        ["segment_id", "combined_score"], ascending=[True, False]

    ).reset_index(drop=True)



    print(f"  [P1] {len(timing_agg)} segment × window combinations scored")

    return timing_agg





# ═════════════════════════════════════════════════════════════

# PHASE 2: Timing & Frequency Resolution (deterministic)

# ═════════════════════════════════════════════════════════════



def resolve_timing(

    iter0_timing_path: str,

    timing_perf: pd.DataFrame,

    delta_rows: list,

) -> pd.DataFrame:

    """

    Update timing_recommendations.csv:

      - Replace recommended_time_window with highest combined_score window

      - Update expected_ctr and expected_engagement to actual means

    """

    print("\n  [P2] Resolving timing recommendations ...")



    if not os.path.exists(iter0_timing_path):

        print(f"  [P2] {iter0_timing_path} not found — skipping")

        return pd.DataFrame()



    timing_df = pd.read_csv(iter0_timing_path)



    if timing_perf.empty:

        print("  [P2] No timing performance data — keeping Iteration 0 as-is")

        timing_df["iteration"] = 1

        return timing_df



    # For each segment, find the top-performing window

    best_windows = (

        timing_perf

        .sort_values(["segment_id", "combined_score"], ascending=[True, False])

        .drop_duplicates(subset=["segment_id"], keep="first")

    )

    best_map = best_windows.set_index("segment_id")[

        ["notification_window", "mean_ctr", "mean_engagement", "combined_score"]

    ].to_dict("index")



    updates = 0

    for idx, row in timing_df.iterrows():

        sid = row.get("segment_id", "")

        if sid not in best_map:

            continue



        best_info = best_map[sid]

        new_window = best_info["notification_window"]

        old_window = row.get("recommended_time_window", "")



        # Update window if different

        if str(old_window) != str(new_window):

            timing_df.at[idx, "recommended_time_window"] = new_window

            delta_rows.append(_delta_row(

                entity_type="segment",

                entity_id=str(sid),

                change_type="timing_shift",

                metric_trigger="window_performance",

                before_value=str(old_window),

                after_value=str(new_window),

                explanation=(

                    f"Shifting to historically highest performing window "

                    f"(combined_score={best_info['combined_score']:.4f}, "

                    f"ctr={best_info['mean_ctr']:.3f}, eng={best_info['mean_engagement']:.3f})"

                ),

            ))

            updates += 1



        # Update expected metrics to actuals

        if "expected_ctr" in timing_df.columns:

            timing_df.at[idx, "expected_ctr"] = round(best_info["mean_ctr"], 4)

        if "expected_engagement" in timing_df.columns:

            timing_df.at[idx, "expected_engagement"] = round(best_info["mean_engagement"], 4)



    timing_df["iteration"] = 1

    print(f"  [P2] {updates} timing window shifts applied")

    return timing_df





# ═════════════════════════════════════════════════════════════

# PHASE 3: Template Evolution (hybrid)

# ═════════════════════════════════════════════════════════════



def evolve_templates(

    iter0_templates: pd.DataFrame,

    exp_df: pd.DataFrame,

    delta_rows: list,

) -> pd.DataFrame:

    global _used_replacement_themes, _generated_titles, _segment_angle_index

    _used_replacement_themes = {}

    _generated_titles = set()

    _segment_angle_index = {}



    print("\n  [P3] Evolving templates ...")



    # ── Normalise segment_id formats before merging ───────────

    def normalise_seg(s):

        if pd.isna(s):

            return s

        s = str(s).strip().lower()

        for prefix in ["seg_", "segment_"]:

            if s.startswith(prefix):

                s = s[len(prefix):]

        return s



    iter0_templates = iter0_templates.copy()

    iter0_templates["_seg_norm"] = iter0_templates["segment_id"].apply(normalise_seg)

    exp_df = exp_df.copy()

    exp_df["_seg_norm"] = exp_df["segment_id"].apply(normalise_seg)



    # ── Try direct template_id merge first ────────────────────

    perf_cols = ["template_id", "ctr", "engagement_rate", "uninstall_rate", "performance_status"]

    available = [c for c in perf_cols if c in exp_df.columns]

    perf_df = exp_df[available].drop_duplicates(subset=["template_id"])



    iter1 = iter0_templates.merge(perf_df, on="template_id", how="left")

    if "primary_goal" not in iter1.columns and "goal" in iter1.columns:

        iter1["primary_goal"] = iter1["goal"]

    elif "primary_goal" in iter1.columns and "goal" in iter1.columns:

        iter1["primary_goal"] = iter1["primary_goal"].fillna(iter1["goal"])



    matched = iter1["performance_status"].notna().sum()

    print(f"  [P3] Direct template_id merge matched {matched}/{len(iter1)} templates")



    # ── Fallback: match on normalised segment_id + theme ──────

    if matched < len(iter1) * 0.5:

        print("  [P3] Low match rate — attempting fallback merge on normalised segment_id + theme ...")



        # Drop failed merge columns

        for col in ["ctr", "engagement_rate", "uninstall_rate", "performance_status"]:

            if col in iter1.columns:

                iter1 = iter1.drop(columns=[col])



        # Strategy A: segment + theme level

        if "theme" in iter1.columns and "theme" in exp_df.columns:

            exp_by_seg_theme = (

                exp_df

                .groupby(["_seg_norm", "theme"])

                .agg(

                    theme_ctr=("ctr", "mean"),

                    theme_engagement=("engagement_rate", "mean"),

                    theme_uninstall=("uninstall_rate", "mean"),

                    theme_samples=("template_id", "count") if "template_id" in exp_df.columns else ("ctr", "count"),

                )

                .reset_index()

            )

             # Classify aggregated theme performance from aggregated metrics,
            # so status remains consistent with displayed CTR/ER values.
            def classify_theme_metrics(ctr_val, eng_val):
                if pd.isna(ctr_val):
                    ctr_val = 0
                if pd.isna(eng_val):
                    eng_val = 0
                if ctr_val >= TEMPLATE_THRESHOLDS["GOOD"]["ctr_min"] and eng_val >= TEMPLATE_THRESHOLDS["GOOD"]["engagement_min"]:
                    return "GOOD"
                elif ctr_val >= TEMPLATE_THRESHOLDS["NEUTRAL"]["ctr_min"] and eng_val >= TEMPLATE_THRESHOLDS["NEUTRAL"]["engagement_min"]:
                    return "NEUTRAL"
                return "BAD"

            exp_by_seg_theme["theme_status"] = exp_by_seg_theme.apply(
                lambda r: classify_theme_metrics(r.get("theme_ctr", 0), r.get("theme_engagement", 0)),
                axis=1,
            )                    

            iter1 = iter1.merge(

                exp_by_seg_theme,

                on=["_seg_norm", "theme"],

                how="left",

            )



            iter1.rename(columns={

                "theme_ctr": "ctr",

                "theme_engagement": "engagement_rate",

                "theme_uninstall": "uninstall_rate",

                "theme_status": "performance_status",

            }, inplace=True)



            matched_theme = iter1["performance_status"].notna().sum()

            print(f"  [P3] Segment+theme merge matched {matched_theme}/{len(iter1)} templates")



        # Strategy B: fill remaining with segment-level aggregate

        still_missing = iter1["performance_status"].isna()

        if still_missing.any():

            seg_perf = exp_df.groupby("_seg_norm").agg(

                seg_ctr=("ctr", "mean"),

                seg_engagement=("engagement_rate", "mean"),

                seg_uninstall=("uninstall_rate", "mean"),

            ).reset_index()



            seg_map = seg_perf.set_index("_seg_norm").to_dict("index")



            for idx in iter1[still_missing].index:

                seg_norm = iter1.at[idx, "_seg_norm"]

                if seg_norm in seg_map:

                    info = seg_map[seg_norm]

                    iter1.at[idx, "ctr"] = info["seg_ctr"]

                    iter1.at[idx, "engagement_rate"] = info["seg_engagement"]

                    iter1.at[idx, "uninstall_rate"] = info["seg_uninstall"]



            print(f"  [P3] Segment-level backfill applied to {still_missing.sum()} remaining rows")



        # Reclassify everything that doesn't have a status yet

        TT = TEMPLATE_THRESHOLDS



        def classify_row(row):

            ctr = row.get("ctr", 0) or 0

            eng = row.get("engagement_rate", 0) or 0

            if pd.isna(ctr):

                ctr = 0

            if pd.isna(eng):

                eng = 0

            if ctr >= TT["GOOD"]["ctr_min"] and eng >= TT["GOOD"]["engagement_min"]:

                return "GOOD"

            elif ctr >= TT["NEUTRAL"]["ctr_min"] and eng >= TT["NEUTRAL"]["engagement_min"]:

                return "NEUTRAL"

            else:

                return "BAD"



        needs_classify = iter1["performance_status"].isna()

        if needs_classify.any():

            iter1.loc[needs_classify, "performance_status"] = iter1[needs_classify].apply(classify_row, axis=1)



        reclassified = iter1["performance_status"].value_counts().to_dict()

        print(f"  [P3] Final classification: {reclassified}")



    # Clean up helper column

    iter1 = iter1.drop(columns=["_seg_norm"], errors="ignore")



    # Fill any remaining NaN

    iter1["performance_status"] = iter1["performance_status"].fillna("NEUTRAL")

    iter1["ctr"] = pd.to_numeric(iter1.get("ctr", 0), errors="coerce").fillna(0.0)

    iter1["engagement_rate"] = pd.to_numeric(iter1.get("engagement_rate", 0), errors="coerce").fillna(0.0)

    iter1["iteration"] = 1



    # ── Collect GOOD templates as references ──────────────────

    good_mask = iter1["performance_status"] == "GOOD"

    ref_cols = [c for c in ["template_id", "segment_id", "lifecycle_stage", "phase_name", "theme", "title_en", "body_en", "ctr"] if c in iter1.columns]

    good_ref_df = iter1[good_mask][ref_cols].copy()

    if "ctr" in good_ref_df.columns:

        good_ref_df = good_ref_df.sort_values("ctr", ascending=False)

    good_refs = good_ref_df.to_dict("records")

    good_count = good_mask.sum()

    print(f"  [P3] GOOD: {good_count} templates -> copied as-is + used as references")



    # ── Handle BAD templates ──────────────────────────────────

    bad_mask = iter1["performance_status"] == "BAD"

    bad_count = bad_mask.sum()

    print(f"  [P3] BAD: {bad_count} templates -> suppressed + theme-swap + LLM rewrite")

    if "source_template_id" not in iter1.columns:

        iter1["source_template_id"] = iter1["template_id"]



    bad_indices = iter1[bad_mask].index.tolist()

    for i, idx in enumerate(bad_indices):

        row = iter1.loc[idx]

        old_theme = row.get("theme", "")

        old_title = row.get("title_en", "")



        # Deterministic: pick replacement theme

        new_theme = _identify_replacement_theme(old_theme, row.get("segment_id", ""), exp_df)



        print(f"    [{i+1}/{bad_count}] Rewriting BAD template {row.get('template_id', idx)}: {old_theme} -> {new_theme}")



        # Segment-aware references (hierarchical fallback) to avoid tone cross-contamination.
        segment_refs = [r for r in good_refs if str(r.get("segment_id")) == str(row.get("segment_id"))]
        best_refs = segment_refs[:3] if len(segment_refs) >= 1 else good_refs[:3]

        # LLM: rewrite with new theme
        improved = _rewrite_bad_template(row, new_theme, best_refs)

        # Mutate template_id for rewritten BAD templates to protect A/B analytics lineage.
        old_id = str(row.get("template_id", idx))
        new_id = f"{old_id}_v2"
        iter1.at[idx, "source_template_id"] = old_id
        iter1.at[idx, "template_id"] = new_id



        # ── FIX: extract rationale from the returned dict ─────

        improvement_rationale = improved.get(

            "improvement_rationale",

            f"Theme swap: {old_theme} → {new_theme}",

        )



        iter1.at[idx, "title_en"] = improved.get("title_en", old_title)

        iter1.at[idx, "body_en"] = improved.get("body_en", "")

        iter1.at[idx, "title_hi"] = improved.get("title_hi", "")

        iter1.at[idx, "body_hi"] = improved.get("body_hi", "")

        iter1.at[idx, "hook_type"] = improved.get("hook_type", new_theme)

        iter1.at[idx, "theme"] = new_theme

        if "cta_en" in iter1.columns:

            iter1.at[idx, "cta_en"] = improved.get("cta_en", "Start Now")

        if "cta_hi" in iter1.columns:

            iter1.at[idx, "cta_hi"] = improved.get("cta_hi", "अभी शुरू करें")



        delta_rows.append(_delta_row(

            entity_type="template",

            entity_id=str(iter1.at[idx, "template_id"]),

            change_type="template_replacement",

            metric_trigger=f"poor_performance_suppression: CTR={row.get('ctr', 0):.2%}, ER={row.get('engagement_rate', 0):.2%}",

            before_value=f"theme={old_theme} | {old_title}",

            after_value=f"theme={new_theme} | {improved.get('title_en', '')}",

            explanation=improvement_rationale,

        ))



    # ── Handle NEUTRAL templates ──────────────────────────────

    neutral_mask = iter1["performance_status"] == "NEUTRAL"

    neutral_count = neutral_mask.sum()

    print(f"  [P3] NEUTRAL: {neutral_count} templates -> same theme, punchier hook (A/B candidate)")



    neutral_indices = iter1[neutral_mask].index.tolist()

    for i, idx in enumerate(neutral_indices):

        row = iter1.loc[idx]

        old_title = row.get("title_en", "")



        print(f"    [{i+1}/{neutral_count}] Iterating NEUTRAL template {row.get('template_id', idx)}")



        improved = _iterate_neutral_template(row, good_refs)



        # ── FIX: extract rationale from the returned dict ─────

        improvement_rationale = improved.get(

            "improvement_rationale",

            "Sharpened hook and urgency",

        )



        iter1.at[idx, "title_en"] = improved.get("title_en", old_title)

        iter1.at[idx, "body_en"] = improved.get("body_en", "")

        iter1.at[idx, "title_hi"] = improved.get("title_hi", "")

        iter1.at[idx, "body_hi"] = improved.get("body_hi", "")

        iter1.at[idx, "hook_type"] = improved.get("hook_type", row.get("theme", ""))

        if "cta_en" in iter1.columns:

            iter1.at[idx, "cta_en"] = improved.get("cta_en", "Practice Now")

        if "cta_hi" in iter1.columns:

            iter1.at[idx, "cta_hi"] = improved.get("cta_hi", "अभ्यास करें")



        delta_rows.append(_delta_row(

            entity_type="template",

            entity_id=str(row.get("template_id", idx)),

            change_type="template_iteration",

            metric_trigger=f"neutral_performance_iteration: CTR={row.get('ctr', 0):.2%}, ER={row.get('engagement_rate', 0):.2%}",

            before_value=old_title,

            after_value=improved.get("title_en", ""),

            explanation=improvement_rationale,

        ))



    print(f"  [P3] Template evolution complete: {good_count} kept, {bad_count} replaced, {neutral_count} iterated")

    return iter1


def _parse_notif_cell(cell_value):
    """
    Parse wide-format schedule cell.
    Supports tuple strings: "(template_id, time_window, channel)"
    and JSON strings containing template/time/channel fields.
    """
    if pd.isna(cell_value):
        return None

    raw = str(cell_value).strip()
    if raw == "":
        return None

    if raw.startswith("(") and raw.endswith(")"):
        inner = raw[1:-1]
        parts = [p.strip() for p in inner.split(",")]
        if len(parts) >= 3:
            channel = ",".join(parts[2:]).strip()
            return {
                "template_id": parts[0],
                "time_window": parts[1],
                "channel": channel,
                "_format": "tuple",
            }

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            template_id = obj.get("template_id", obj.get("template"))
            time_window = obj.get("time_window", obj.get("time"))
            channel = obj.get("channel")
            if template_id is not None:
                return {
                    "template_id": str(template_id),
                    "time_window": time_window,
                    "channel": channel,
                    "_format": "json",
                    "_obj": obj,
                }
    except Exception:
        pass

    return {
        "template_id": None,
        "time_window": None,
        "channel": None,
        "_format": "raw",
        "_raw": raw,
    }


def _pack_notif_cell(parsed):
    """Repack parsed notification cell back to original shape."""
    if parsed is None:
        return np.nan

    fmt = parsed.get("_format")
    if fmt == "tuple":
        return f"({parsed.get('template_id', '')}, {parsed.get('time_window', '')}, {parsed.get('channel', '')})"

    if fmt == "json":
        obj = dict(parsed.get("_obj", {}))
        if "template_id" in obj:
            obj["template_id"] = parsed.get("template_id")
        elif "template" in obj:
            obj["template"] = parsed.get("template_id")

        if "time_window" in obj:
            obj["time_window"] = parsed.get("time_window")
        elif "time" in obj:
            obj["time"] = parsed.get("time_window")

        if "channel" in obj:
            obj["channel"] = parsed.get("channel")
        return json.dumps(obj, ensure_ascii=False)

    return parsed.get("_raw", "")


# ═════════════════════════════════════════════════════════════

# PHASE 4: Schedule Regeneration (deterministic)

# ═════════════════════════════════════════════════════════════



def regenerate_schedule(

    iter0_schedule_path: str,

    iter1_templates: pd.DataFrame,

    iter1_timing: pd.DataFrame,

    guardrails: dict,

    delta_rows: list,

    output_dir: str,

) -> pd.DataFrame:

    """

    Re-map updated templates + timings to users.

    Apply guardrail penalty: -2 daily notifications for breached segments.

    """

    print("\n  [P4] Regenerating user notification schedule ...")



    if not os.path.exists(iter0_schedule_path):

        print(f"  [P4] {iter0_schedule_path} not found — skipping schedule regeneration")

        return pd.DataFrame()



    schedule_df = pd.read_csv(iter0_schedule_path)



    # ── Build lookup maps ─────────────────────────────────────

    template_lookup = {}

    if "template_id" in iter1_templates.columns:

        for _, tmpl in iter1_templates.iterrows():

            new_id = str(tmpl.get("template_id", "")).strip()

            if new_id and new_id.lower() != "nan":

                template_lookup[new_id] = tmpl

            old_id = str(tmpl.get("source_template_id", "")).strip()

            if old_id and old_id.lower() != "nan":

                template_lookup[old_id] = tmpl



    timing_lookup = {}

    if not iter1_timing.empty and "segment_id" in iter1_timing.columns:

        best_timing = (

            iter1_timing

            .sort_values(

                ["segment_id", "expected_ctr" if "expected_ctr" in iter1_timing.columns else "segment_id"],

                ascending=[True, False],

            )

            .drop_duplicates(subset=["segment_id"], keep="first")

        )

        for _, row in best_timing.iterrows():

            timing_lookup[row["segment_id"]] = row.get("recommended_time_window", "evening")



    # ── Apply guardrail frequency reduction (wide format) ─────

    breached_segments = {sid for sid, info in guardrails.items() if info["guardrail_breached"]}

    notif_cols = [c for c in schedule_df.columns if str(c).startswith("notif_")]

    reduced_cells_by_segment = {}

    if breached_segments:

        print(f"  [P4] Applying guardrail penalty (-2 notifs) to {len(breached_segments)} segments: {breached_segments}")

    for idx, row in schedule_df.iterrows():

        sid = row.get("segment_id")

        if sid in breached_segments:

            populated_cols = [c for c in notif_cols if pd.notna(row[c]) and str(row[c]).strip() != ""]

            if len(populated_cols) >= 3:

                cols_to_drop = populated_cols[-2:]

                for col in cols_to_drop:

                    schedule_df.at[idx, col] = np.nan

                reduced_cells_by_segment[sid] = reduced_cells_by_segment.get(sid, 0) + len(cols_to_drop)

    for sid, dropped_cells in reduced_cells_by_segment.items():

        delta_rows.append(_delta_row(

            entity_type="segment",

            entity_id=str(sid),

            change_type="frequency_reduction",

            metric_trigger=f"uninstall_rate_exceeded_{GUARDRAIL_UNINSTALL_RATE:.0%}",

            before_value="wide_notif_schedule",

            after_value=f"last_2_notifs_cleared_per_row ({dropped_cells} cells)",

            explanation=(

                f"Segment {sid} avg uninstall_rate="

                f"{guardrails[sid]['avg_uninstall_rate']:.3f} > {GUARDRAIL_UNINSTALL_RATE}. "

                f"Cleared last two populated notif columns in wide-format schedule rows."

            ),

        ))



    # ── Update template IDs + timings in schedule ─────────────

    updates = 0

    for idx, row in schedule_df.iterrows():

        sid = row.get("segment_id", "")

        if len(notif_cols) > 0:

            for col in notif_cols:

                parsed = _parse_notif_cell(row.get(col, np.nan))

                if parsed is None:

                    continue

                changed = False

                old_tid = parsed.get("template_id")

                if old_tid is not None:

                    lookup_tid = str(old_tid).strip()

                    if lookup_tid in template_lookup:

                        tmpl = template_lookup[lookup_tid]

                        new_tid = str(tmpl.get("template_id", lookup_tid)).strip()

                        if new_tid and new_tid != lookup_tid:

                            parsed["template_id"] = new_tid

                            changed = True

                if sid in timing_lookup and parsed.get("time_window") is not None:

                    old_window = str(parsed.get("time_window")).strip()

                    new_window = str(timing_lookup[sid]).strip()

                    if old_window != new_window:

                        parsed["time_window"] = new_window

                        changed = True

                if changed:

                    schedule_df.at[idx, col] = _pack_notif_cell(parsed)

                    updates += 1

        else:

            # Backward compatibility for long-format schedules.
            tid = str(row.get("template_id", "")).strip()

            if tid in template_lookup:

                tmpl = template_lookup[tid]

                if "template_id" in schedule_df.columns:

                    new_tid = str(tmpl.get("template_id", tid)).strip()

                    if new_tid and new_tid != tid:

                        schedule_df.at[idx, "template_id"] = new_tid

                        updates += 1

                if "message_title" in schedule_df.columns:

                    schedule_df.at[idx, "message_title"] = tmpl.get("title_en", "")

                if "message_body" in schedule_df.columns:

                    schedule_df.at[idx, "message_body"] = tmpl.get("body_en", "")

            if sid in timing_lookup and "time_window" in schedule_df.columns:

                old_window = row.get("time_window", "")

                new_window = timing_lookup[sid]

                if str(old_window) != str(new_window):

                    schedule_df.at[idx, "time_window"] = new_window

                    updates += 1



    print(f"  [P4] Updated {updates} time window entries in schedule")

    if "user_id" in schedule_df.columns:
        print(f"  [P4] Final schedule: {len(schedule_df)} rows for {schedule_df['user_id'].nunique()} users")
    else:
        print(f"  [P4] Final schedule: {len(schedule_df)} rows (segment-level schedule format)")

    return schedule_df





# ═════════════════════════════════════════════════════════════

# PHASE 5: Delta Report Helper

# ═════════════════════════════════════════════════════════════



def _delta_row(

    entity_type: str,

    entity_id: str,

    change_type: str,

    metric_trigger: str,

    before_value: str,

    after_value: str,

    explanation: str,

) -> dict:

    return {

        "entity_type":    entity_type,

        "entity_id":      entity_id,

        "change_type":    change_type,

        "metric_trigger": metric_trigger,

        "before_value":   before_value,

        "after_value":    after_value,

        "explanation":    explanation,

        "timestamp":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

    }





# ═════════════════════════════════════════════════════════════

# MAIN PIPELINE

# ═════════════════════════════════════════════════════════════



def run_learning_engine(

    iter0_dir: str   = OUTPUT_DIR_0,

    experiment_path: str = None,

    iter1_dir: str   = OUTPUT_DIR_1,

) -> tuple:

    """

    Main orchestrator for the 5-phase learning engine.



    Called from main.py as:

        run_learning_engine(tmpl_path, timing_path, OUTPUT_DIR_1)

    where the first two args are file paths.  We accept that gracefully:

      - If iter0_dir looks like a file path, derive the directory from it.

      - If experiment_path is missing/invalid (or is actually a timing CSV),

        fall back to

        EXPERIMENT_RESULTS_PATH from config.

    """

    def _csv_columns(path: str) -> set[str]:

        try:

            return set(pd.read_csv(path, nrows=0).columns)

        except Exception:

            return set()



    def _looks_like_experiment_results_csv(path: str) -> bool:

        cols = {c.strip() for c in _csv_columns(path)}

        has_template = any(c in cols for c in _EXPERIMENT_COLUMN_ALIASES["template_id"])

        has_segment = any(c in cols for c in _EXPERIMENT_COLUMN_ALIASES["segment_id"])

        has_ctr = ("ctr" in cols) or {"total_opens", "total_sends"}.issubset(cols)

        has_engagement = ("engagement_rate" in cols) or {"total_engagements", "total_sends"}.issubset(cols)

        has_uninstall = "uninstall_rate" in cols

        return has_template and has_segment and has_ctr and has_engagement and has_uninstall



    # ── Normalise arguments (handle main.py's call convention) ──

    # main.py passes (templates_csv_path, timing_csv_path, output_dir)

    # We need (iter0_directory, experiment_csv_path, iter1_directory)

    iter0_templates_path = None

    timing_path_override = None



    if iter0_dir and os.path.isfile(iter0_dir):

        iter0_templates_path = iter0_dir

        iter0_dir = os.path.dirname(iter0_dir) or OUTPUT_DIR_0



    # If the second arg is actually timing_recommendations.csv (main.py's call),

    # ignore it as experiment_path and use it as an override for Phase 2.

    if experiment_path and os.path.isfile(experiment_path):

        base = os.path.basename(experiment_path).lower()

        if base == "timing_recommendations.csv" or "timing" in base:

            timing_path_override = experiment_path

            experiment_path = None

        elif experiment_path.lower().endswith(".csv") and not _looks_like_experiment_results_csv(experiment_path):

            timing_path_override = experiment_path

            experiment_path = None



    if experiment_path is None or not os.path.exists(experiment_path):

        # Try standard locations

        candidates = [

            os.path.join(iter0_dir, "experiment_results.csv"),

            EXPERIMENT_RESULTS_PATH,

            os.path.join(".", "experiment_results.csv"),

        ]

        experiment_path = None

        for c in candidates:

            if os.path.exists(c):

                experiment_path = c

                break

        if experiment_path is None:

            print(f"  [ABORT] experiment_results.csv not found in any expected location.")

            print(f"          Searched: {candidates}")

            return pd.DataFrame(), pd.DataFrame()



    os.makedirs(iter1_dir, exist_ok=True)

    delta_rows = []



    print(f"\n  iter0_dir       : {iter0_dir}")

    print(f"  experiment_path : {experiment_path}")

    print(f"  iter1_dir       : {iter1_dir}")



    # ═══════════════════════════════════════════════════════════

    # PHASE 1: Data Ingestion & State Evaluation

    # ═══════════════════════════════════════════════════════════

    print("\n" + "=" * 60)

    print("  PHASE 1: Data Ingestion & State Evaluation")

    print("=" * 60)



    exp_df     = load_and_classify_experiments(experiment_path)

    guardrails = evaluate_segment_guardrails(exp_df)

    timing_perf = aggregate_timing_performance(exp_df)



    breached_segments = [

        sid for sid, info in guardrails.items() if info["guardrail_breached"]

    ]

    for seg in breached_segments:

        print(f"    [WARN] {seg}: {guardrails[seg]['avg_uninstall_rate']:.2%}")






    # ═══════════════════════════════════════════════════════════

    # PHASE 2: Timing & Frequency Resolution

    # ═══════════════════════════════════════════════════════════

    print("\n" + "=" * 60)

    print("  PHASE 2: Timing & Frequency Resolution")

    print("=" * 60)



    timing_path = timing_path_override or os.path.join(iter0_dir, "timing_recommendations.csv")

    iter1_timing = resolve_timing(timing_path, timing_perf, delta_rows)



    if not iter1_timing.empty:

        save_csv(iter1_timing, "timing_recommendations.csv", iter1_dir)



    # ═══════════════════════════════════════════════════════════

    # PHASE 3: Template Evolution

    # ═══════════════════════════════════════════════════════════

    print("\n" + "=" * 60)

    print("  PHASE 3: Template Evolution")

    print("=" * 60)



    tmpl_path = iter0_templates_path or os.path.join(iter0_dir, "message_templates.csv")

    if not os.path.exists(tmpl_path):

        print(f"  [ABORT] {tmpl_path} not found.")

        return pd.DataFrame(), pd.DataFrame()



    iter0_templates = pd.read_csv(tmpl_path)

    iter1_templates = evolve_templates(iter0_templates, exp_df, delta_rows)



    save_csv(iter1_templates, "message_templates.csv", iter1_dir)



    # ═══════════════════════════════════════════════════════════

    # PHASE 4: Schedule Regeneration + Guardrail Enforcement

    # ═══════════════════════════════════════════════════════════

    print("\n" + "=" * 60)

    print("  PHASE 4: Schedule Regeneration")

    print("=" * 60)



    schedule_path = os.path.join(iter0_dir, "user_notification_schedule.csv")

    iter1_schedule = regenerate_schedule(

        schedule_path,

        iter1_templates,

        iter1_timing if not iter1_timing.empty else pd.DataFrame(),

        guardrails,

        delta_rows,

        iter1_dir,

    )



    if not iter1_schedule.empty:

        save_csv(iter1_schedule, "user_notification_schedule.csv", iter1_dir)



    # Copy unchanged files from iter0 → iter1

    for fname in ["user_segments.csv"]:

        src = os.path.join(iter0_dir, fname)

        dst = os.path.join(iter1_dir, fname)

        if os.path.exists(src) and not os.path.exists(dst):

            shutil.copy2(src, dst)

            print(f"  [copy] {src} -> {dst}")



    # ═══════════════════════════════════════════════════════════

    # PHASE 5: Delta Report Compilation

    # ═══════════════════════════════════════════════════════════

    print("\n" + "=" * 60)

    print("  PHASE 5: Delta Report Compilation")

    print("=" * 60)



    delta_df = pd.DataFrame(delta_rows) if delta_rows else pd.DataFrame(columns=[

        "entity_type", "entity_id", "change_type", "metric_trigger",

        "before_value", "after_value", "explanation", "timestamp",

    ])



    # Summary statistics

    good_count    = int((iter1_templates["performance_status"] == "GOOD").sum())    if "performance_status" in iter1_templates.columns else 0

    neutral_count = int((iter1_templates["performance_status"] == "NEUTRAL").sum()) if "performance_status" in iter1_templates.columns else 0

    bad_count     = int((iter1_templates["performance_status"] == "BAD").sum())     if "performance_status" in iter1_templates.columns else 0



    summary = {

        "total_templates":              len(iter1_templates),

        "good_templates":               good_count,

        "neutral_templates_iterated":   neutral_count,

        "bad_templates_replaced":       bad_count,

        "timing_shifts":                sum(1 for d in delta_rows if d["change_type"] == "timing_shift"),

        "frequency_reductions":         sum(1 for d in delta_rows if d["change_type"] == "frequency_reduction"),

        "guardrail_breached_segments":  breached_segments,

        "total_delta_changes":          len(delta_rows),

    }



    print(f"\n  [SUMMARY] {json.dumps(summary, indent=2)}")



    delta_report_dir = os.path.dirname(os.path.normpath(iter0_dir))

    save_csv(delta_df, "learning_delta_report.csv", delta_report_dir)



    print(f"\n  [DONE] Task 3 complete - {len(delta_rows)} changes logged")

    print(f"     Outputs in: {iter1_dir}/")



    return iter1_templates, delta_df