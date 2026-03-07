# learning_engine.py
# ─────────────────────────────────────────────────────────────
# Task 3: Execution & Self-Learning
#
# Ingests experiment_results.csv provided by SpeakX, then:
#   1. Classifies templates as GOOD / NEUTRAL / BAD
#   2. Learns optimal timing patterns per segment
#   3. Suppresses BAD templates, promotes GOOD as references
#   4. Regenerates improved Iteration 1 outputs
#   5. Produces learning_delta_report.csv documenting every change
# ─────────────────────────────────────────────────────────────

import os
import json
import pandas as pd
from datetime import datetime

from llm import llm, safe_parse_json, save_csv, save_json
from data_loader import load_data, add_derived_signals
from kb_loader   import load_kb
from config import (
    EXPERIMENT_RESULTS_PATH,
    TEMPLATE_THRESHOLDS,
    OUTPUT_DIR_0,
    OUTPUT_DIR_1,
)


# ── Step 1: Load & classify experiment results ────────────────

def load_and_classify_experiments(path: str = EXPERIMENT_RESULTS_PATH) -> pd.DataFrame:
    """
    Load experiment_results.csv and classify each template as GOOD / NEUTRAL / BAD.
    Expected columns: template_id, segment_id, lifecycle_stage, goal, theme,
                      notification_window, total_sends, total_opens, total_engagements,
                      ctr, engagement_rate, uninstall_rate
    """
    print("  [L1] Loading experiment results ...")
    df = pd.read_csv(path)

    # Coerce numeric columns
    for col in ["ctr", "engagement_rate", "uninstall_rate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # Classify per thresholds
    def classify(row):
        ctr  = row.get("ctr", 0)
        eng  = row.get("engagement_rate", 0)
        good = TEMPLATE_THRESHOLDS["GOOD"]
        neut = TEMPLATE_THRESHOLDS["NEUTRAL"]
        if ctr >= good["ctr_min"] and eng >= good["engagement_min"]:
            return "GOOD"
        elif ctr >= neut["ctr_min"] and eng >= neut["engagement_min"]:
            return "NEUTRAL"
        else:
            return "BAD"

    df["performance_status"] = df.apply(classify, axis=1)
    counts = df["performance_status"].value_counts().to_dict()
    print(f"  [L1] Classification results: {counts}")
    return df


# ── Step 2: Learn timing patterns ─────────────────────────────

def learn_timing_patterns(exp_df: pd.DataFrame) -> dict:
    """
    Analyse which notification_window performed best per segment.
    Returns dict: {segment_id: {lifecycle_stage: best_window}}
    """
    print("  [L2] Learning timing patterns ...")
    patterns = {}

    if "notification_window" not in exp_df.columns:
        return patterns

    for (sid, stage), grp in exp_df.groupby(["segment_id", "lifecycle_stage"]):
        window_perf = grp.groupby("notification_window")["ctr"].mean().sort_values(ascending=False)
        if len(window_perf) > 0:
            best = window_perf.index[0]
            patterns.setdefault(sid, {})[stage] = {
                "best_window":  best,
                "avg_ctr":      round(window_perf.iloc[0], 4),
                "window_ranking": window_perf.to_dict(),
            }

    print(f"  [L2] Learned timing for {len(patterns)} segments")
    return patterns


# ── Step 3: Generate Iteration 1 improved templates ──────────

def _gen_improved_template(
    original_row: pd.Series,
    good_refs:    list[dict],
    reason:       str,
) -> dict:
    """Use LLM to generate one improved template based on GOOD references."""

    refs_block = "\n".join(
        f'  - [{r.get("theme","")}] EN: "{r.get("title_en","")} — {r.get("body_en","")}" | CTR: {r.get("ctr","?")}'
        for r in good_refs[:3]
    )

    raw = llm(
        system="You are a notification copywriter improving underperforming messages. Output ONLY valid JSON.",
        prompt=f"""
KNOWLEDGE BANK (use Ethical Guidelines and feature descriptions when rewriting):
{load_kb()}

Original template that performed {reason}:
  template_id   : {original_row.get('template_id', '')}
  segment       : {original_row.get('segment_id', '')} — {original_row.get('lifecycle_stage', '')}
  theme         : {original_row.get('theme', '')}
  title_en      : {original_row.get('title_en', '')}
  body_en       : {original_row.get('body_en', '')}
  CTR           : {original_row.get('ctr', 0):.2%}
  engagement    : {original_row.get('engagement_rate', 0):.2%}

High-performing GOOD templates from same/similar segment for reference:
{refs_block}

Rewrite the template. Fix what made it underperform. Use a stronger hook,
clearer CTA, more personalised language. Keep the Hindi version accurate.

Return ONLY valid JSON:
{{
  "title_en":  "<improved English title — max 8 words>",
  "body_en":   "<improved English body — max 20 words>",
  "title_hi":  "<improved Hindi title — max 8 words>",
  "body_hi":   "<improved Hindi body — max 20 words>",
  "hook_type": "<Octolysis drive name>",
  "cta_en":    "<call-to-action in English — max 4 words>",
  "cta_hi":    "<call-to-action in Hindi — max 4 words>",
  "improvement_rationale": "<1 sentence: what you changed and why>"
}}"""
    )
    return safe_parse_json(raw, fallback={
        "title_en":  "Your English awaits!",
        "body_en":   "Practice for just 5 minutes today and maintain your streak.",
        "title_hi":  "आपकी अंग्रेजी इंतजार कर रही है!",
        "body_hi":   "आज सिर्फ 5 मिनट अभ्यास करें।",
        "hook_type": "Loss Avoidance",
        "cta_en":    "Start Now",
        "cta_hi":    "अभी शुरू करें",
        "improvement_rationale": "Strengthened loss-avoidance hook and shortened CTA.",
    })


# ── Step 4: Build delta report ────────────────────────────────

def _delta_row(
    entity_type:    str,
    entity_id:      str,
    change_type:    str,
    metric_trigger: str,
    before_value:   str,
    after_value:    str,
    explanation:    str,
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


# ── Main learning pipeline ────────────────────────────────────

def run_learning_engine(
    iter0_templates_path: str = None,
    iter0_timing_path:    str = None,
    output_dir: str = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Full Task 3 learning pipeline.

    Args:
        iter0_templates_path : path to Iteration 0 message_templates.csv
        iter0_timing_path    : path to Iteration 0 timing_recommendations.csv
        output_dir           : where to write Iteration 1 outputs

    Returns:
        (updated_templates_df, delta_report_df)
    """
    out0   = OUTPUT_DIR_0
    out1   = output_dir or OUTPUT_DIR_1
    os.makedirs(out1, exist_ok=True)

    delta_rows = []

    # ── 1. Load experiment results ─────────────────────────────
    if not os.path.exists(EXPERIMENT_RESULTS_PATH):
        print(f"  [warn] {EXPERIMENT_RESULTS_PATH} not found — skipping learning engine.")
        return pd.DataFrame(), pd.DataFrame()

    exp_df = load_and_classify_experiments(EXPERIMENT_RESULTS_PATH)

    # Save the classified experiment results
    save_csv(exp_df, "experiment_results_classified.csv", out1)

    # ── 2. Load Iteration 0 templates ─────────────────────────
    tmpl_path = iter0_templates_path or os.path.join(out0, "message_templates.csv")
    if not os.path.exists(tmpl_path):
        print(f"  [warn] {tmpl_path} not found.")
        return exp_df, pd.DataFrame()

    iter0_templates = pd.read_csv(tmpl_path)

    # ── 3. Classify & merge performance into templates ─────────
    perf_cols = ["template_id", "ctr", "engagement_rate", "uninstall_rate", "performance_status"]
    available = [c for c in perf_cols if c in exp_df.columns]
    perf_df   = exp_df[available].drop_duplicates(subset=["template_id"])

    iter1_templates = iter0_templates.merge(perf_df, on="template_id", how="left")
    iter1_templates["performance_status"] = iter1_templates["performance_status"].fillna("NEUTRAL")
    iter1_templates["ctr"]                = iter1_templates.get("ctr", pd.Series(dtype=float)).fillna(0.0)
    iter1_templates["iteration"]          = 1

    # ── 4. Collect GOOD templates as references ────────────────
    good_refs = (
        iter1_templates[iter1_templates["performance_status"] == "GOOD"]
        [["template_id", "theme", "title_en", "body_en", "ctr"]]
        .to_dict("records")
    )
    print(f"  [L3] Found {len(good_refs)} GOOD templates to use as references")

    # ── 5. Improve BAD templates ───────────────────────────────
    bad_mask   = iter1_templates["performance_status"] == "BAD"
    bad_count  = bad_mask.sum()
    print(f"  [L3] Improving {bad_count} BAD templates ...")

    for idx in iter1_templates[bad_mask].index:
        row     = iter1_templates.loc[idx]
        old_en  = row.get("title_en", "")
        improved = _gen_improved_template(row, good_refs, "BAD")

        iter1_templates.at[idx, "title_en"]  = improved.get("title_en", old_en)
        iter1_templates.at[idx, "body_en"]   = improved.get("body_en", "")
        iter1_templates.at[idx, "title_hi"]  = improved.get("title_hi", "")
        iter1_templates.at[idx, "body_hi"]   = improved.get("body_hi", "")
        iter1_templates.at[idx, "hook_type"] = improved.get("hook_type", "")

        delta_rows.append(_delta_row(
            entity_type="template",
            entity_id=row.get("template_id", str(idx)),
            change_type="content_rewrite",
            metric_trigger=f"CTR={row.get('ctr',0):.2%}, ER={row.get('engagement_rate',0):.2%} → BAD",
            before_value=old_en,
            after_value=improved.get("title_en", ""),
            explanation=improved.get("improvement_rationale", "Improved hook and CTA"),
        ))

    # ── 6. Update timing recommendations ──────────────────────
    timing_path = iter0_timing_path or os.path.join(out0, "timing_recommendations.csv")
    timing_patterns = learn_timing_patterns(exp_df)

    if os.path.exists(timing_path) and timing_patterns:
        timing_df = pd.read_csv(timing_path)

        for sid, stage_map in timing_patterns.items():
            for stage, info in stage_map.items():
                mask = (timing_df["segment_id"] == sid) & (timing_df["lifecycle_stage"] == stage)
                if mask.sum() > 0:
                    old_w = timing_df.loc[mask, "optimal_window_1"].iloc[0]
                    new_w = info["best_window"]
                    if old_w != new_w:
                        timing_df.loc[mask, "optimal_window_1"] = new_w
                        delta_rows.append(_delta_row(
                            entity_type="timing",
                            entity_id=f"{sid}_{stage}",
                            change_type="window_update",
                            metric_trigger=f"Learned from experiment data: avg_ctr={info['avg_ctr']:.3f}",
                            before_value=old_w,
                            after_value=new_w,
                            explanation=f"Window {new_w} had highest avg CTR ({info['avg_ctr']:.2%}) for {sid}×{stage}",
                        ))

        save_csv(timing_df, "timing_recommendations.csv", out1)

    # ── 7. Save Iteration 1 templates ─────────────────────────
    save_csv(iter1_templates, "message_templates.csv", out1)

    # ── 8. Copy unchanged files to Iter 1 folder ──────────────
    for fname in ["user_segments.csv", "user_notification_schedule.csv"]:
        src = os.path.join(out0, fname)
        dst = os.path.join(out1, fname)
        if os.path.exists(src) and not os.path.exists(dst):
            import shutil
            shutil.copy2(src, dst)
            print(f"  [copy] {src} → {dst}")

    # ── 9. Save delta report ───────────────────────────────────
    delta_df = pd.DataFrame(delta_rows) if delta_rows else pd.DataFrame(columns=[
        "entity_type", "entity_id", "change_type", "metric_trigger",
        "before_value", "after_value", "explanation", "timestamp"
    ])

    # Add summary stats to delta report
    summary = {
        "total_templates":     len(iter1_templates),
        "good_templates":      int((iter1_templates["performance_status"] == "GOOD").sum()),
        "neutral_templates":   int((iter1_templates["performance_status"] == "NEUTRAL").sum()),
        "bad_templates_fixed": bad_count,
        "timing_updates":      sum(len(v) for v in timing_patterns.values()),
        "total_delta_changes": len(delta_rows),
    }
    print(f"\n  [summary] Learning delta: {summary}")

    save_csv(delta_df, "learning_delta_report.csv", out1)
    save_json(summary, "learning_summary.json", out1)

    return iter1_templates, delta_df
