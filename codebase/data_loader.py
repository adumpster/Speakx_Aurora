# data_loader.py
# ─────────────────────────────────────────────────────────────────────────────
# Unified data loader — merges both teammate contributions.
#
# Public API used by generators:
#   load_and_profile(path)  →  DataProfile   (main entry point)
#   load_data(path)         →  pd.DataFrame  (raw + cleaned)
#   add_derived_signals(df) →  pd.DataFrame  (adds propensity/risk columns)
#   build_data_summary(df)  →  str           (text injected into LLM prompts)
#   extract_features(df)    →  list[dict]
#
# DataProfile bundles everything so generators only need one import.
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass
import pandas as pd
from config import USER_DATA_PATH


# ── Required schema ───────────────────────────────────────────────────────────
REQUIRED_COLUMNS = [
    "user_id", "lifecycle_stage", "days_since_signup",
    "age_band", "region",
    "sessions_last_7d", "exercises_completed_7d",
    "streak_current", "coins_balance",
    "preferred_hour", "notif_open_rate_30d", "motivation_score",
]

FLOAT_COLUMNS = ["notif_open_rate_30d", "motivation_score", "coins_balance"]
INT_COLUMNS   = ["days_since_signup", "sessions_last_7d", "exercises_completed_7d",
                 "streak_current", "preferred_hour"]


# ── DataProfile dataclass ─────────────────────────────────────────────────────

@dataclass
class DataProfile:
    df:               pd.DataFrame   # cleaned + scored DataFrame
    feature_cols:     list           # list of feature_* column names
    lifecycle_stages: list           # unique lifecycle stage values
    summary:          str            # text block injected into LLM prompts


# ── Load & validate ───────────────────────────────────────────────────────────

def load_data(path: str = USER_DATA_PATH) -> pd.DataFrame:
    """Read CSV, coerce dtypes, fill missing values, return clean DataFrame."""
    df = pd.read_csv(path)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        print(f"  [warn] Missing expected columns: {missing}")

    # Normalise boolean feature_* columns (may arrive as "TRUE"/"FALSE" strings)
    bool_cols = [c for c in df.columns if c.startswith("feature_")]
    for col in bool_cols:
        df[col] = (
            df[col].astype(str).str.strip().str.upper()
            .map({"TRUE": True, "1": True, "FALSE": False, "0": False})
            .fillna(False)
        )

    # Coerce numeric columns
    for col in FLOAT_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    for col in INT_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # Normalise lifecycle_stage
    df["lifecycle_stage"] = df["lifecycle_stage"].str.lower().str.strip()

    print(f"  [data] Loaded {len(df)} users | "
          f"stages: {df['lifecycle_stage'].value_counts().to_dict()}")
    return df


# ── Derived signals ───────────────────────────────────────────────────────────

def add_derived_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add computed columns used by segmentation and scheduling.
    Column names kept consistent with segmentation_engine expectations.
    """
    df = df.copy()

    # activeness_score — RFM-based composite (0-1)
    #
    # R (Recency)   — notification open rate in last 30 days:
    #                 high open rate ⟹ recently engaged
    # F (Frequency) — sessions in last 7 days (capped at 14 = 2/day):
    #                 how often the user shows up
    # M (Magnitude) — depth of engagement: exercises done + streak held
    #                 captures the *quality* and continuity of each visit
    #
    # Weights: F carries most signal (0.40) because raw visit frequency is
    # the strongest predictor of short-term retention; R and M share 0.30
    # each to reward recent engagement and sustained depth.
    r_score    = df["notif_open_rate_30d"].clip(0, 1)
    f_score    = df["sessions_last_7d"].clip(0, 14) / 14
    m_exer     = df["exercises_completed_7d"].clip(0, 21) / 21
    m_streak   = df["streak_current"].clip(0, 30) / 30
    m_score    = 0.5 * m_exer + 0.5 * m_streak
    df["activeness_score"] = (
        0.30 * r_score + 0.40 * f_score + 0.30 * m_score
    ).round(3)

    # churn_risk_score (0-1)
    inactive_flag = df["lifecycle_stage"].isin(["churned", "inactive"]).astype(float)
    low_sessions  = (df["sessions_last_7d"] == 0).astype(float)
    low_streak    = (df["streak_current"]   == 0).astype(float)
    low_notif     = (1 - df["notif_open_rate_30d"]).clip(0, 1)
    df["churn_risk_score"] = (
        0.35 * inactive_flag + 0.25 * low_sessions +
        0.20 * low_streak    + 0.20 * low_notif
    ).round(3)

    # ── Domain-agnostic propensities ─────────────────────────────────────────
    # Auto-discover every feature_* boolean column in the CSV.
    # propensity_<feature_name> = 0.6 * usage_flag + 0.4 * motivation_score
    #
    # Formula rationale:
    #   60% usage signal  — did the user actually engage with this feature?
    #   40% motivation    — general receptiveness / intent to engage
    #
    # Domain agnosticism:
    #   No feature names are hardcoded. Swap the CSV for any domain and
    #   all propensity columns auto-adapt to whatever feature_* cols exist.
    #   e.g. feature_ai_tutor_used      → propensity_ai_tutor_used
    #        feature_leaderboard_viewed  → propensity_leaderboard_viewed
    #        feature_checkout_completed  → propensity_checkout_completed  (FinTech)
    #        feature_report_viewed       → propensity_report_viewed       (SaaS)

    motiv_norm   = df["motivation_score"].clip(0, 1) if "motivation_score" in df.columns else pd.Series(0.5, index=df.index)
    feature_cols = [c for c in df.columns if c.startswith("feature_")]

    for col in feature_cols:
        feature_name = col[len("feature_"):]        # strip "feature_" prefix
        prop_col     = f"propensity_{feature_name}" # propensity_ai_tutor_used etc.
        usage_flag   = df[col].astype(float)
        df[prop_col] = (0.6 * usage_flag + 0.4 * motiv_norm).round(3)

    # Fallback: if no feature_* columns exist, add a generic engagement propensity
    if not feature_cols:
        df["propensity_engagement"] = motiv_norm.round(3)

    return df


# ── Data summary for LLM context ─────────────────────────────────────────────

def build_data_summary(df: pd.DataFrame) -> str:
    """
    Compact text summary of the behavioural dataset.
    Injected into every LLM prompt as grounding context.
    """
    bool_cols = [c for c in df.columns if c.startswith("feature_")]
    total     = len(df)
    stage_counts = df["lifecycle_stage"].value_counts().to_dict()

    feature_stats = {}
    for col in bool_cols:
        fname = col.replace("feature_", "")
        feature_stats[fname] = round(df[col].sum() / total * 100, 1)

    lines = [
        "=== BEHAVIORAL DATA SUMMARY ===",
        f"Total users: {total}",
        f"Lifecycle stages: {stage_counts}",
        f"Age distribution: {df['age_band'].value_counts().to_dict()}",
        f"Region distribution: {df['region'].value_counts().to_dict()}",
        "",
        "--- Activity ---",
        f"Avg sessions/7d: {round(df['sessions_last_7d'].mean(), 2)}",
        f"Avg exercises/7d: {round(df['exercises_completed_7d'].mean(), 2)}",
        f"Avg current streak: {round(df['streak_current'].mean(), 2)} days",
        f"Avg coins balance: {round(df['coins_balance'].mean(), 2)}",
        f"Avg notification open rate (30d): {round(df['notif_open_rate_30d'].mean(), 3)}",
        f"Avg motivation score: {round(df['motivation_score'].mean(), 3)}",
        f"Peak preferred hour: {int(df['preferred_hour'].mode()[0])}:00",
        "",
        "--- Feature Usage (% users TRUE) ---",
    ]
    for fname, pct in feature_stats.items():
        lines.append(f"  {fname}: {pct}%")

    lines += ["", "--- Per-Stage Averages ---"]
    for stage in sorted(df["lifecycle_stage"].unique()):
        sub = df[df["lifecycle_stage"] == stage]
        if len(sub) == 0:
            continue
        lines.append(
            f"  {stage} (n={len(sub)}): "
            f"sessions={round(sub['sessions_last_7d'].mean(),1)}, "
            f"exercises={round(sub['exercises_completed_7d'].mean(),1)}, "
            f"streak={round(sub['streak_current'].mean(),1)}, "
            f"notif_open={round(sub['notif_open_rate_30d'].mean(),3)}, "
            f"motiv={round(sub['motivation_score'].mean(),3)}"
        )

    return "\n".join(lines)


# ── Feature discovery ─────────────────────────────────────────────────────────

def extract_features(df: pd.DataFrame) -> list:
    """Return one dict per feature_* column with usage stats."""
    feature_cols = [c for c in df.columns if c.startswith("feature_")]
    features = []
    for col in feature_cols:
        name  = col[len("feature_"):]
        mask  = df[col].astype(bool)
        stages = sorted(df.loc[mask, "lifecycle_stage"].dropna().unique().tolist())
        features.append({
            "column":           col,
            "name":             name,
            "lifecycle_stages": stages,
            "usage_rate":       round(float(mask.mean()), 3),
            "usage_pct":        round(mask.sum() / len(df) * 100, 1),
            "user_count":       int(mask.sum()),
        })
    return features


# ── Main entry point ──────────────────────────────────────────────────────────

def load_and_profile(path: str = USER_DATA_PATH) -> DataProfile:
    """
    Load CSV, clean, add derived signals, build summary, return DataProfile.
    This is the single entry point used by all generators.
    """
    print(f"[data] Loading '{path}' ...")
    df = load_data(path)
    df = add_derived_signals(df)

    feature_cols     = [c for c in df.columns if c.startswith("feature_")]
    lifecycle_stages = sorted(df["lifecycle_stage"].dropna().unique().tolist())
    summary          = build_data_summary(df)

    print(f"[data] {len(df)} users | "
          f"{len(feature_cols)} feature cols | "
          f"stages: {lifecycle_stages}")

    return DataProfile(
        df=df,
        feature_cols=feature_cols,
        lifecycle_stages=lifecycle_stages,
        summary=summary,
    )