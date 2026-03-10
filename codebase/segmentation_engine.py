# segmentation_engine.py
# ─────────────────────────────────────────────────────────────
# Generates: user_segments.csv — NO LLM, fully deterministic.
#
# DOMAIN AGNOSTIC:
#   - Propensity columns are discovered dynamically from the CSV
#     (any feature_* column → propensity_<feature_name>)
#   - Segment rules use activeness_score + lifecycle_stage +
#     dominant_propensity (whichever propensity_* col is highest)
#   - No feature names hardcoded anywhere
#
# Segmentation logic:
#   Step 1 — Compute activeness_score, churn_risk, propensities
#             (done in data_loader.add_derived_signals)
#   Step 2 — Find each user's dominant_propensity dynamically
#   Step 3 — Assign activeness band: high / moderate / low
#   Step 4 — Split each band by lifecycle_stage
#   Step 5 — Within each lifecycle×band cell, sub-split by
#             dominant_propensity rank
#   Step 6 — Compute all metadata from data statistics
#   Step 7 — Output sorted by segment_id
#
# Segments (13 MECE + 1 catch-all):
#   HIGH (≥0.7):      SEG_01 top-propensity paid, SEG_02 other paid,
#                     SEG_03 high trial
#   MODERATE (0.4–0.7): SEG_04 high-propensity paid, SEG_05 low-propensity paid,
#                       SEG_06 motivated trial, SEG_07 low-motivation trial
#   LOW (<0.4):       SEG_08 paid, SEG_09 trial,
#                     SEG_10 recent churned (<45d), SEG_11 deep churned (≥45d),
#                     SEG_12 inactive high-propensity, SEG_13 inactive low-propensity
#   CATCH-ALL:        SEG_14 Unclassified
# ─────────────────────────────────────────────────────────────

import pandas as pd
from llm         import save_csv
from data_loader import load_data, add_derived_signals


# ── Octolysis drive lookup keyed by segment_id ────────────────
# These are strategy defaults — not domain-specific feature names.

SEGMENT_META = {
    "SEG_01": ("Accomplishment",   "Empowerment",      "motivating",    "Deepen top-feature usage with personalised challenges and milestone badges.",              "Maximise W1 exercise completion through feature-led daily challenges."),
    "SEG_02": ("Loss Avoidance",   "Ownership",        "competitive",   "Protect engagement with streak reminders and ownership of progress assets.",               "Increase monthly retention via streak continuity."),
    "SEG_03": ("Scarcity",         "Empowerment",      "urgent-warm",   "Create urgency around trial expiry; highlight transformation stories to convert.",          "Convert trial to paid by demonstrating value within D0-D7."),
    "SEG_04": ("Ownership",        "Unpredictability", "encouraging",   "Nudge toward daily habit with feature-specific rewards and coin incentives.",               "Build exercise habit to improve W1 retention post-conversion."),
    "SEG_05": ("Unpredictability", "Loss Avoidance",   "friendly",      "Re-ignite curiosity through surprise content and unpredictable reward drops.",              "Increase session frequency to cross habit-formation threshold."),
    "SEG_06": ("Scarcity",         "Epic Meaning",     "motivating",    "Reinforce conversion intent with scarcity messaging and quick-win exercises.",              "Accelerate trial-to-paid conversion with urgency messaging."),
    "SEG_07": ("Empowerment",      "Unpredictability", "curious",       "Lower friction with shorter sessions and empowerment-focused choice messaging.",            "Reduce trial drop-off by raising curiosity and lowering entry barrier."),
    "SEG_08": ("Loss Avoidance",   "Epic Meaning",     "concerned",     "Send loss-avoidance alerts for streak and progress; offer a re-engagement bonus.",          "Prevent paid churn by reactivating before 30-day inactivity mark."),
    "SEG_09": ("Scarcity",         "Empowerment",      "urgent-warm",   "Send a single high-impact trial expiry message; offer an easy entry-point lesson.",         "Salvage trial conversion with a decisive last-chance intervention."),
    "SEG_10": ("Epic Meaning",     "Loss Avoidance",   "empathetic",    "Use empathetic win-back narrative; remind of progress made before churning.",               "Win back recently churned users before they become deep churned."),
    "SEG_11": ("Epic Meaning",     "Empowerment",      "gentle",        "Lead with epic meaning and career transformation; avoid pressure-heavy tones.",             "Attempt re-acquisition through brand story and aspiration hooks."),
    "SEG_12": ("Loss Avoidance",   "Unpredictability", "warm",          "Gentle streak-loss warning with a feature-specific re-entry prompt for engaged users.",     "Reactivate high-propensity inactive users before permanent churn."),
    "SEG_13": ("Epic Meaning",     "Scarcity",         "neutral-warm",  "Broader re-engagement appeal with low-friction entry point and aspirational messaging.",    "Reactivate low-propensity inactive users; recover monthly retention numbers."),
    "SEG_14": ("Accomplishment",   "Epic Meaning",     "neutral",       "Apply default balanced engagement strategy; monitor for better segment fit.",               "Drive exercise completion; reclassify as data accumulates."),
}

SEGMENT_NAMES = {
    "SEG_01": "High-Active Power Users",
    "SEG_02": "High-Active Streak Keepers",
    "SEG_03": "High-Active Trial Converters",
    "SEG_04": "Moderate-Active Feature Enthusiasts",
    "SEG_05": "Moderate-Active Casual Paid",
    "SEG_06": "Moderate-Active Trial Activators",
    "SEG_07": "Moderate-Active Trial Fence-Sitters",
    "SEG_08": "Low-Active At-Risk Paid",
    "SEG_09": "Low-Active Cold Trial",
    "SEG_10": "Recent Churned",
    "SEG_11": "Deep Churned",
    "SEG_12": "Inactive High-Propensity",
    "SEG_13": "Inactive Low-Propensity",
    "SEG_14": "Unclassified",
}


# ── Dynamic propensity helpers ────────────────────────────────

def _get_propensity_cols(df: pd.DataFrame) -> list:
    """Return all propensity_* columns present in the DataFrame."""
    return [c for c in df.columns if c.startswith("propensity_")]


def _dominant_propensity(row: pd.Series, prop_cols: list) -> tuple:
    """
    Return (dominant_propensity_name, score) for a single row.
    Works with any number of propensity_* columns — fully dynamic.
    """
    if not prop_cols:
        return "none", 0.0
    scores = {col: row[col] for col in prop_cols}
    dom_col = max(scores, key=scores.get)
    return dom_col.replace("propensity_", ""), round(scores[dom_col], 3)


def _add_dominant_propensity(df: pd.DataFrame) -> pd.DataFrame:
    """Add dominant_propensity and dominant_propensity_score columns."""
    prop_cols = _get_propensity_cols(df)
    if not prop_cols:
        df["dominant_propensity"]       = "none"
        df["dominant_propensity_score"] = 0.0
        return df

    results = df.apply(
        lambda r: pd.Series(_dominant_propensity(r, prop_cols)),
        axis=1
    )
    results.columns = ["dominant_propensity", "dominant_propensity_score"]
    return pd.concat([df, results], axis=1)


# ── Segment assignment ────────────────────────────────────────

def _compute_percentile_bands(df: pd.DataFrame) -> tuple:
    """
    Compute data-driven activeness band thresholds using percentiles.

    Bottom 33 % of users  → 'low'
    Middle 34 %           → 'moderate'
    Top 33 %              → 'high'

    Using percentiles instead of fixed values (0.4 / 0.7) ensures the
    three bands are always populated regardless of the score distribution,
    improving segment coverage across all lifecycle stages.
    """
    p_low  = float(df["activeness_score"].quantile(0.33))
    p_high = float(df["activeness_score"].quantile(0.67))
    return p_low, p_high


def _assign_segment(row: pd.Series) -> str:
    """
    Assign a segment_id based on activeness band + lifecycle stage.
    Reads the pre-computed 'activeness_band' column (low/moderate/high)
    set by percentile cuts — no hardcoded score thresholds here.
    Uses dominant_propensity to further split within paid segments.
    All logic is data-driven — no feature names hardcoded.
    """
    band      = row.get("activeness_band", "low")
    stage     = row["lifecycle_stage"]
    dom_score = row.get("dominant_propensity_score", 0)

    # ── HIGH band ────────────────────────────────────────────
    if band == "high":
        if stage == "paid":
            return "SEG_01" if dom_score >= 0.6 else "SEG_02"
        if stage == "trial":
            return "SEG_03"

    # ── MODERATE band ────────────────────────────────────────
    elif band == "moderate":
        if stage == "paid":
            return "SEG_04" if dom_score >= 0.4 else "SEG_05"
        if stage == "trial":
            return "SEG_06" if row.get("motivation_score", 0) >= 0.5 else "SEG_07"

    # ── LOW band ─────────────────────────────────────────────
    else:
        if stage == "paid":
            return "SEG_08"
        if stage == "trial":
            return "SEG_09"
        if stage == "churned":
            return "SEG_10" if row.get("days_since_signup", 999) < 45 else "SEG_11"
        if stage == "inactive":
            return "SEG_12" if dom_score >= 0.4 else "SEG_13"

    return "SEG_14"  # catch-all


# ── Key behaviour signal (pure statistics) ────────────────────

def _key_signal(df_seg: pd.DataFrame, prop_cols: list) -> str:
    avg_act   = df_seg["activeness_score"].mean()
    avg_churn = df_seg["churn_risk_score"].mean()
    avg_motiv = df_seg["motivation_score"].mean() if "motivation_score" in df_seg.columns else 0

    # Find dominant propensity by average across segment (dynamic)
    if prop_cols:
        prop_avgs = {c.replace("propensity_", ""): df_seg[c].mean() for c in prop_cols}
        dom = max(prop_avgs, key=prop_avgs.get)
        dom_val = prop_avgs[dom]
        prop_str = f"dominant propensity: {dom} ({dom_val:.2f})"
    else:
        prop_str = "no feature propensity data"

    stage_dist = df_seg["lifecycle_stage"].value_counts().to_dict()
    top_stage  = max(stage_dist, key=stage_dist.get)

    return (
        f"{top_stage.capitalize()} users — activeness {avg_act:.2f}, "
        f"churn risk {avg_churn:.2f}, motivation {avg_motiv:.2f}; {prop_str}."
    )


# ── Main entry point ──────────────────────────────────────────

def gen_user_segments(df=None, output_dir: str = None):
    """
    Assign all users to MECE segments. No LLM — fully deterministic.
    Propensity columns are discovered dynamically from the DataFrame.

    Returns:
        user_seg_df    : per-user DataFrame sorted by segment_id
        seg_summary_df : per-segment summary sorted by segment_id
    """
    print("\n[4/5] Generating: user_segments.csv  (no LLM — pure feature extraction)")

    if df is None:
        df = load_data()

    df = add_derived_signals(df)

    # Discover propensity columns (whatever feature_* cols exist in this CSV)
    prop_cols = _get_propensity_cols(df)
    print(f"  [seg] Propensity columns found: {[c.replace('propensity_','') for c in prop_cols]}")

    # Add dominant propensity per user
    df = _add_dominant_propensity(df)

    # Percentile-based activeness band — must be computed BEFORE segment
    # assignment so _assign_segment can read the band string directly.
    p_low, p_high = _compute_percentile_bands(df)
    print(f"  [seg] Activeness percentile thresholds: "
          f"low<{p_low:.3f} ≤ moderate<{p_high:.3f} ≤ high")
    df["activeness_band"] = pd.cut(
        df["activeness_score"],
        bins=[-0.001, p_low, p_high, 1.001],
        labels=["low", "moderate", "high"]
    ).astype(str)

    # Assign segment (reads activeness_band, not raw score thresholds)
    print("  [seg] Assigning MECE segments ...")
    df["segment_id"]   = df.apply(_assign_segment, axis=1)
    df["segment_name"] = df["segment_id"].map(SEGMENT_NAMES).fillna("Unclassified")

    seg_counts = df["segment_id"].value_counts().sort_index().to_dict()
    print(f"  [seg] Distribution: {seg_counts}")

    # ── Per-segment summary (pure stats) ─────────────────────
    seg_rows = []
    for sid in sorted(df["segment_id"].unique()):
        df_s  = df[df["segment_id"] == sid]
        name  = SEGMENT_NAMES.get(sid, "Unclassified")
        meta  = SEGMENT_META.get(sid, ("Accomplishment", "Epic Meaning", "neutral",
                                       "Apply default strategy.", "Drive exercise completion."))
        primary_drive, secondary_drive, tone, strategy, ns_lever = meta

        # Per-propensity averages (dynamic — works for any number of features)
        prop_avgs = {c: round(df_s[c].mean(), 3) for c in prop_cols}

        row_dict = {
            "segment_id":                sid,
            "segment_name":              name,
            "activeness_band":           df_s["activeness_band"].mode()[0] if len(df_s) else "low",
            "user_count":                len(df_s),
            "lifecycle_stages":          "|".join(sorted(df_s["lifecycle_stage"].unique())),
            "avg_activeness_score":      round(df_s["activeness_score"].mean(), 3),
            "avg_churn_risk_score":      round(df_s["churn_risk_score"].mean(), 3),
            "avg_motivation_score":      round(df_s["motivation_score"].mean(), 3) if "motivation_score" in df_s.columns else None,
            "dominant_propensity":       df_s["dominant_propensity"].mode()[0] if len(df_s) else "none",
            "primary_octolysis_drive":   primary_drive,
            "secondary_octolysis_drive": secondary_drive,
            "recommended_tone":          tone,
            "key_behaviour_signal":      _key_signal(df_s, prop_cols),
            "communication_strategy":    strategy,
            "north_star_lever":          ns_lever,
        }
        # Add per-feature propensity averages dynamically
        row_dict.update({f"avg_{c}": v for c, v in prop_avgs.items()})
        seg_rows.append(row_dict)

    seg_summary_df = pd.DataFrame(seg_rows).sort_values("segment_id").reset_index(drop=True)

    # ── Per-user output ───────────────────────────────────────
    # Keep only essential columns — no raw behavioral noise.
    # Individual propensity_* columns are dropped; only the
    # dominant_propensity name + score are kept (single summary
    # signal regardless of how many features exist in the CSV).
    core_cols = [
        "segment_id",
        "segment_name",
        "user_id",
        "lifecycle_stage",
        "age_band",
        "region",
        "activeness_score",
        "churn_risk_score",
        "activeness_band",
        "dominant_propensity",
        "dominant_propensity_score",
    ]

    user_seg_df = df[[c for c in core_cols if c in df.columns]].copy()

    # Sort by segment_id then user_id
    user_seg_df = user_seg_df.sort_values(["segment_id", "user_id"]).reset_index(drop=True)

    save_csv(user_seg_df, "user_segments.csv", output_dir)

    print(f"  [seg] {len(user_seg_df)} users across {len(seg_summary_df)} segments")
    for _, r in seg_summary_df.iterrows():
        print(
            f"    {r['segment_id']}  {r['segment_name']:35s} "
            f"n={r['user_count']:3d}  act={r['avg_activeness_score']:.2f}  "
            f"band={r['activeness_band']}  dominant={r['dominant_propensity']}"
        )

    return user_seg_df, seg_summary_df