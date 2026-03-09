# goal_builder.py
# ─────────────────────────────────────────────────────────────
# Generates: segment_goals.csv
#
# Phase-aware goal builder with 11 granular lifecycle phases:
#
# TRIAL (D1–D7):
#   Phase 1 — Activation & Value Discovery        (Days 1–2)
#   Phase 2 — Habit Formation & Early Engagement  (Days 3–5)
#   Phase 3 — The Conversion Push                 (Days 6–7)
#
# PAID (D8–D30):
#   Phase 4 — Premium Affirmation                 (Days 8–10)
#   Phase 5 — Deep Immersion                      (Days 11–15)
#   Phase 6 — Social & Expansion Drive            (Days 16–20)
#   Phase 7 — Overcoming the Slump                (Days 21–25)
#   Phase 8 — ROI Demonstration                   (Days 26–28)
#   Phase 9 — Retention & Renewal                 (Days 29–30)
#
# CHURNED (D31+):
#   Phase 10 — The Win-Back
#
# INACTIVE (D X+):
#   Phase 11 — The Low-Friction Re-engagement
#
# Architecture: domain-agnostic — swap KB + CSV, same orchestrator.
#   octolysis_drives → overridden at runtime from tone_hook_matrix.json
#   key_nudges       → derived at runtime from feature_goal_map.json
# ─────────────────────────────────────────────────────────────

import json
import os
import re
import pandas as pd

from llm       import save_csv
from kb_loader import load_kb


# ── Phase scaffold ────────────────────────────────────────────
# octolysis_drives and key_nudges are intentionally left empty here.
# They are filled dynamically at runtime from tone_hook_matrix.json
# and feature_goal_map.json respectively, so the file stays
# domain-agnostic — no product name or feature name is hardcoded.

PHASE_CONFIG = {
    # ── TRIAL ──────────────────────────────────────────────────
    "trial_phase1_activation": {
        "lifecycle": "trial",
        "phase_number": 1,
        "phase_name": "Activation & Value Discovery",
        "day_range": "Days 1–2",
        "primary_goal": "Deliver the 'aha moment' — make the user feel immediate value within the first 48 hours.",
        "strategic_intent": (
            "First impressions are permanent. The user signed up with hope; "
            "our job is to convert that hope into a felt experience of progress. "
            "Reduce friction to zero, surface the most impressive feature instantly, "
            "and anchor identity: 'I am someone who does this.'"
        ),
        "octolysis_drives": [],   # populated from tone_matrix at runtime
        "key_nudges": [],         # populated from feature_goal_map at runtime
    },
    "trial_phase2_habit": {
        "lifecycle": "trial",
        "phase_number": 2,
        "phase_name": "Habit Formation & Early Engagement",
        "day_range": "Days 3–5",
        "primary_goal": "Establish a daily usage pattern — 3 consecutive active days locks in behavioral habit.",
        "strategic_intent": (
            "Habit loops need repetition in the same context. "
            "Tie the app to an existing ritual (morning coffee, commute). "
            "Use streak mechanics, progress visibility, and social proof "
            "to make skipping feel costlier than engaging."
        ),
        "octolysis_drives": [],
        "key_nudges": [],
    },
    "trial_phase3_conversion": {
        "lifecycle": "trial",
        "phase_number": 3,
        "phase_name": "The Conversion Push",
        "day_range": "Days 6–7",
        "primary_goal": "Convert trial user to paid subscriber before trial expiry.",
        "strategic_intent": (
            "Scarcity is real — trial ends in hours. "
            "Lead with value already received, then anchor on what they'll lose. "
            "Remove friction: one-tap upgrade, payment pre-filled. "
            "Urgency must feel earned, not manufactured."
        ),
        "octolysis_drives": [],
        "key_nudges": [],
    },
    # ── PAID ───────────────────────────────────────────────────
    "paid_phase4_affirmation": {
        "lifecycle": "paid",
        "phase_number": 4,
        "phase_name": "Premium Affirmation",
        "day_range": "Days 8–10",
        "primary_goal": "Validate the purchase decision — eliminate buyer's remorse, unlock premium features immediately.",
        "strategic_intent": (
            "The first 72 hours post-conversion is the highest-churn-risk window. "
            "The user needs to feel the paid experience is visibly better. "
            "Surface exclusive content, celebrate the upgrade, "
            "and reinforce identity: 'You are now a committed user.'"
        ),
        "octolysis_drives": [],
        "key_nudges": [],
    },
    "paid_phase5_immersion": {
        "lifecycle": "paid",
        "phase_number": 5,
        "phase_name": "Deep Immersion",
        "day_range": "Days 11–15",
        "primary_goal": "Drive deep feature adoption — unlock high-value features that improve long-term retention.",
        "strategic_intent": (
            "Surface area of the product = stickiness. "
            "Users who use 3+ features churn significantly less. "
            "Guide users through features they haven't discovered, "
            "using personalized recommendations based on their propensity profile."
        ),
        "octolysis_drives": [],
        "key_nudges": [],
    },
    "paid_phase6_social": {
        "lifecycle": "paid",
        "phase_number": 6,
        "phase_name": "Social & Expansion Drive",
        "day_range": "Days 16–20",
        "primary_goal": "Leverage social mechanics and referrals to deepen engagement and expand user network.",
        "strategic_intent": (
            "Users with friends in the product have significantly higher retention. "
            "Activate community features, referral programs, and social rankings. "
            "Turn the individual journey into a shared one — "
            "social accountability is the strongest long-term retention lever."
        ),
        "octolysis_drives": [],
        "key_nudges": [],
    },
    "paid_phase7_slump": {
        "lifecycle": "paid",
        "phase_number": 7,
        "phase_name": "Overcoming the Slump",
        "day_range": "Days 21–25",
        "primary_goal": "Detect and counter mid-subscription disengagement before it becomes churn.",
        "strategic_intent": (
            "The 3-week mark is where motivation naturally dips — "
            "novelty has worn off, results aren't yet dramatic. "
            "Proactively surface wins they've had, re-anchor their 'why', "
            "and reduce session friction to the absolute minimum."
        ),
        "octolysis_drives": [],
        "key_nudges": [],
    },
    "paid_phase8_roi": {
        "lifecycle": "paid",
        "phase_number": 8,
        "phase_name": "ROI Demonstration",
        "day_range": "Days 26–28",
        "primary_goal": "Show measurable, concrete improvement to justify renewal.",
        "strategic_intent": (
            "Renewal decisions are rational at this stage. "
            "Lead with data: performance score delta, sessions completed, streak length, "
            "peer ranking improvement. Make the ROI undeniable. "
            "Frame continuation as investment, not expense."
        ),
        "octolysis_drives": [],
        "key_nudges": [],
    },
    "paid_phase9_renewal": {
        "lifecycle": "paid",
        "phase_number": 9,
        "phase_name": "Retention & Renewal",
        "day_range": "Days 29–30",
        "primary_goal": "Secure renewal before subscription lapses with minimal friction.",
        "strategic_intent": (
            "Auto-renewal should feel like a celebration, not a chore. "
            "For users considering lapsing: loss framing on streak, coins, rank. "
            "For committed users: reward loyalty with a bonus or early access. "
            "Personalize based on churn_risk_score — high risk gets more aggressive re-engagement."
        ),
        "octolysis_drives": [],
        "key_nudges": [],
    },
    # ── CHURNED ────────────────────────────────────────────────
    "churned_phase10_winback": {
        "lifecycle": "churned",
        "phase_number": 10,
        "phase_name": "The Win-Back",
        "day_range": "Day 31+",
        "primary_goal": "Re-activate churned users through nostalgia, urgency, and irresistible re-entry offers.",
        "strategic_intent": (
            "Churned users left for a reason — find it. "
            "Lead with nostalgia and what they've missed. "
            "Use limited-time win-back offers (discount, free week). "
            "Lower re-entry bar dramatically: one-tap resume, "
            "saved progress, no re-onboarding friction."
        ),
        "octolysis_drives": [],
        "key_nudges": [],
    },
    # ── INACTIVE ───────────────────────────────────────────────
    "inactive_phase11_reengagement": {
        "lifecycle": "inactive",
        "phase_number": 11,
        "phase_name": "The Low-Friction Re-engagement",
        "day_range": "Day X+",
        "primary_goal": "Trigger one micro-action with zero friction to re-establish presence in user's routine.",
        "strategic_intent": (
            "Inactive users have high cognitive barriers to return — "
            "don't ask for a full session, ask for one tap. "
            "Micro-commitments rebuild habits. "
            "Lead with a compelling hook (new feature, community event, personal milestone), "
            "not a generic 'we miss you'. Be specific, be brief, be curiosity-gap-driven."
        ),
        "octolysis_drives": [],
        "key_nudges": [],
    },
}

# Map lifecycle → applicable phases
LIFECYCLE_PHASE_MAP = {
    "trial":    ["trial_phase1_activation", "trial_phase2_habit", "trial_phase3_conversion"],
    "paid":     ["paid_phase4_affirmation", "paid_phase5_immersion", "paid_phase6_social",
                 "paid_phase7_slump", "paid_phase8_roi", "paid_phase9_renewal"],
    "churned":  ["churned_phase10_winback"],
    "inactive": ["inactive_phase11_reengagement"],
}


# ── Tone matrix helpers ───────────────────────────────────────

def _index_tone_matrix(tone_matrix: dict) -> dict:
    """
    Build a dict keyed by lifecycle_stage from tone_hook_matrix.json.
    Also indexes the hook_taxonomy by drive name for example phrases.

    Returns:
        {
          "trial": {
            "primary_drives": [...],
            "secondary_drives": [...],
            "allowed_tones": [...],
            "hook_intensity": "high",
            "hook_examples": { "Epic Meaning": ["Join 1M+...", ...], ... }
          },
          ...
        }
    """
    index = {}

    # Build hook example lookup from hook_taxonomy
    hook_examples = {}
    for entry in tone_matrix.get("hook_taxonomy", []):
        drive = entry.get("core_drive", "")
        hook_examples[drive] = entry.get("example_phrases", [])

    for entry in tone_matrix.get("matrix", []):
        stage = entry.get("lifecycle_stage", "")
        if not stage:
            continue
        index[stage] = {
            "primary_drives":   entry.get("primary_drives",   []),
            "secondary_drives": entry.get("secondary_drives", []),
            "allowed_tones":    entry.get("allowed_tones",    []),
            "hook_intensity":   entry.get("hook_intensity",   "medium"),
            "hook_examples":    hook_examples,
        }

    return index


def _drives_for_lifecycle(tone_index: dict, lifecycle: str) -> list:
    """Return ordered drive list (primary + secondary) for a lifecycle stage."""
    ctx = tone_index.get(lifecycle, {})
    return ctx.get("primary_drives", []) + ctx.get("secondary_drives", [])


# ── Feature goal map helpers ──────────────────────────────────

def _derive_feature_nudges(feature_goal_map: dict, lifecycle: str) -> list:
    """
    Build a list of nudge strings for a lifecycle stage from feature_goal_map.json.
    Pulls from each feature's propensity_levers and sub_goals where the lifecycle
    is in the feature's lifecycle_stage list.
    """
    nudges = []
    for feat in feature_goal_map.get("feature_goal_map", []):
        if lifecycle not in feat.get("lifecycle_stage", []):
            continue
        name = feat.get("feature", "the feature")
        for lever in feat.get("propensity_levers", []):
            nudges.append(f"{name}: {lever}")
        for sg in feat.get("sub_goals", []):
            nudges.append(sg)
    return nudges if nudges else [
        "Trigger first action using the user's highest-propensity feature",
        "Reinforce yesterday's win with an incremental challenge",
        "Surface a feature the user hasn't explored yet",
    ]


# ── Disk loaders ─────────────────────────────────────────────

def _load_feature_goal_map(output_dir: str) -> dict:
    path = os.path.join(output_dir or ".", "feature_goal_map.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        print(f"  [goals] Loaded feature_goal_map: {path}")
        return data
    print(f"  [goals] WARN: feature_goal_map.json not found at {path} — nudges will use defaults")
    return {}


def _load_tone_matrix(output_dir: str) -> dict:
    path = os.path.join(output_dir or ".", "allowed_tone_hook_matrix.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        print(f"  [goals] Loaded tone_hook_matrix: {path}")
        return data
    print(f"  [goals] WARN: allowed_tone_hook_matrix.json not found at {path} — drives will use phase defaults")
    return {}


# ── Helpers ───────────────────────────────────────────────────

def safe_parse_json(raw: str, fallback: dict) -> dict:
    """Robustly parse JSON from LLM output, stripping markdown fences."""
    try:
        clean = re.sub(r"```(?:json)?|```", "", raw).strip()
        return json.loads(clean)
    except Exception:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return fallback


def _call_llm(system: str, prompt: str) -> str:
    """
    LLM call — uses the project-local Ollama wrapper (llm.py).
    """
    try:
        from llm import llm  # project-local Ollama wrapper
        return llm(system=system, prompt=prompt)
    except Exception as e:
        print(f"  [LLM ERROR] {e}")
        return "{}"


# ── Core goal generator ───────────────────────────────────────

def _build_phase_goal(
    segment_id: str,
    segment_name: str,
    dominant_propensity: str,
    phase_key: str,
    phase_cfg: dict,
    stats: dict,
    north_star: dict,
    kb_text: str,
) -> dict:
    """
    One LLM call → one row for segment_goals.csv.
    phase_cfg already has octolysis_drives and key_nudges populated
    from tone_matrix and feature_goal_map before this call.
    """
    ns_metric = north_star.get("inferred_north_star", {}).get("metric_name", "Monthly Retention")
    ns_def    = north_star.get("inferred_north_star", {}).get("definition", "")

    octolysis_str = ", ".join(phase_cfg["octolysis_drives"]) if phase_cfg["octolysis_drives"] else "Accomplishment, Empowerment"
    nudges_str    = "\n".join(f"  • {n}" for n in phase_cfg["key_nudges"]) if phase_cfg["key_nudges"] else "  • Drive engagement with personalized feature hooks"

    prompt = f"""
KNOWLEDGE BANK:
{kb_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SEGMENT CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Segment ID          : {segment_id}
Segment Name        : {segment_name}
Dominant Propensity : {dominant_propensity}

BEHAVIORAL STATS (from CSV):
  avg_activeness_score  : {stats.get('avg_activeness', 0.5):.3f}
  avg_churn_risk_score  : {stats.get('avg_churn_risk', 0.3):.3f}
  avg_motivation_score  : {stats.get('avg_motivation', 0.5):.3f}
  avg_exercises_7d      : {stats.get('avg_exercises', 5):.1f}
  avg_sessions_7d       : {stats.get('avg_sessions', 3):.1f}
  avg_notif_open_rate   : {stats.get('avg_notif_open', 0.4):.3f}
  avg_streak_current    : {stats.get('avg_streak', 2):.1f}
  avg_coins_balance     : {stats.get('avg_coins', 50):.0f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase Number        : {phase_cfg['phase_number']} of 11
Phase Name          : {phase_cfg['phase_name']}
Lifecycle Stage     : {phase_cfg['lifecycle'].upper()}
Day Range           : {phase_cfg['day_range']}
Phase Primary Goal  : {phase_cfg['primary_goal']}
Strategic Intent    : {phase_cfg['strategic_intent']}
Octolysis Drives    : {octolysis_str}
Suggested Nudges    :
{nudges_str}

North Star Metric   : {ns_metric} — {ns_def}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR TASK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Design a precise, data-driven goal plan for this SEGMENT × PHASE combination.
Be specific to the segment's propensity ({dominant_propensity}) and activeness level.
Consider their churn risk ({stats.get('avg_churn_risk', 0.3):.2f}) when calibrating urgency.

Return ONLY valid JSON (no markdown, no explanation):
{{
  "primary_goal": "<single most important goal for this segment in this phase>",
  "sub_goals": [
    "<sub_goal_1 — specific, measurable>",
    "<sub_goal_2 — specific, measurable>",
    "<sub_goal_3 — specific, measurable>"
  ],
  "day_focus": {{
    "day_1": "<exact first-day nudge for this phase>",
    "day_2": "<second day focus>",
    "day_mid": "<mid-phase focus (if phase > 2 days)>",
    "day_end": "<final day of phase focus — transition to next phase>"
  }},
  "primary_octolysis_drive": "<single most relevant Octolysis drive for this segment×phase>",
  "hook_template": "<a concrete notification hook line using the Octolysis drive>",
  "success_metric": "<measurable outcome that signals goal achieved>",
  "failure_signal": "<behavioral signal that means goal is failing>",
  "escalation_action": "<what to do when failure signal detected>",
  "personalization_lever": "<what behavioral data field to personalize on most for this segment>"
}}"""

    raw = _call_llm(
        system=(
            "You are an expert product journey designer specialising in behavioral psychology "
            "and notification orchestration. You think in Octolysis drives, churn signals, and "
            "user psychology. Output ONLY valid JSON — no preamble, no markdown fences."
        ),
        prompt=prompt,
    )

    drives = phase_cfg["octolysis_drives"]
    nudges = phase_cfg["key_nudges"]

    fallback = {
        "primary_goal":          phase_cfg["primary_goal"],
        "sub_goals":             [
            f"Increase {dominant_propensity} engagement",
            "Complete at least 1 core action per day",
            "Maintain streak continuity",
        ],
        "day_focus": {
            "day_1":   f"Trigger first action — leverage {dominant_propensity} propensity",
            "day_2":   "Reinforce yesterday's win, add incremental challenge",
            "day_mid": "Sustain momentum, introduce social element",
            "day_end": "Prepare transition — preview next phase value",
        },
        "primary_octolysis_drive":  drives[0] if drives else "Accomplishment",
        "hook_template":            nudges[0] if nudges else f"Complete one action today to build your {dominant_propensity} habit",
        "success_metric":           "exercises_completed_7d >= 3 AND sessions_last_7d >= 3",
        "failure_signal":           "sessions_last_7d == 0 for 2 consecutive days",
        "escalation_action":        "Send Loss Avoidance notification with streak-save hook",
        "personalization_lever":    dominant_propensity,
    }

    result = safe_parse_json(raw, fallback)

    sub_goals = result.get("sub_goals", fallback["sub_goals"])
    day_focus  = result.get("day_focus", fallback["day_focus"])

    return {
        # Identity
        "segment_id":               segment_id,
        "segment_name":             segment_name,
        "dominant_propensity":      dominant_propensity,
        "lifecycle_stage":          phase_cfg["lifecycle"],
        # Phase metadata
        "phase_number":             phase_cfg["phase_number"],
        "phase_name":               phase_cfg["phase_name"],
        "day_range":                phase_cfg["day_range"],
        # Goals
        "primary_goal":             result.get("primary_goal",  phase_cfg["primary_goal"]),
        "sub_goal_1":               sub_goals[0] if len(sub_goals) > 0 else "",
        "sub_goal_2":               sub_goals[1] if len(sub_goals) > 1 else "",
        "sub_goal_3":               sub_goals[2] if len(sub_goals) > 2 else "",
        # Day-level focus
        "day_focus_day1":           day_focus.get("day_1",   ""),
        "day_focus_day2":           day_focus.get("day_2",   ""),
        "day_focus_mid":            day_focus.get("day_mid", ""),
        "day_focus_end":            day_focus.get("day_end", ""),
        # Psychology
        "primary_octolysis_drive":  result.get("primary_octolysis_drive",  drives[0] if drives else "Accomplishment"),
        "hook_template":            result.get("hook_template",             nudges[0] if nudges else ""),
        # Signals
        "success_metric":           result.get("success_metric",           fallback["success_metric"]),
        "failure_signal":           result.get("failure_signal",           fallback["failure_signal"]),
        "escalation_action":        result.get("escalation_action",        fallback["escalation_action"]),
        "personalization_lever":    result.get("personalization_lever",    dominant_propensity),
        # Segment stats (for downstream consumers)
        "stat_avg_activeness":      round(stats.get("avg_activeness", 0.5), 3),
        "stat_avg_churn_risk":      round(stats.get("avg_churn_risk",  0.3), 3),
        "stat_avg_motivation":      round(stats.get("avg_motivation",  0.5), 3),
    }


# ── Public API ────────────────────────────────────────────────

def gen_segment_goals(
    user_segments_df: pd.DataFrame = None,
    df: pd.DataFrame = None,
    north_star: dict = None,
    output_dir: str = None,
    feature_goal_map: dict = None,
    tone_matrix: dict = None,
) -> pd.DataFrame:
    """
    Build segment_goals.csv with 11 granular lifecycle phases.

    Args:
        user_segments_df : output of gen_user_segments (segment_id, segment_name,
                           user_id, lifecycle_stage, dominant_propensity, activeness_score,
                           churn_risk_score columns expected)
        df               : raw behavioral DataFrame with motivation_score,
                           exercises_completed_7d, sessions_last_7d, etc.
        north_star       : output of gen_north_star
        output_dir       : override output directory (default: current dir)
        feature_goal_map : output of gen_feature_goal_map — used to derive key_nudges
        tone_matrix      : output of gen_tone_hook_matrix — used to derive octolysis_drives
    """
    print("\n[Goal Builder] Generating segment_goals.csv — 11-phase architecture")

    # ── Load raw behavioral data ───────────────────────────────
    if df is None:
        try:
            from data_loader import load_data, add_derived_signals
            df = add_derived_signals(load_data())
        except ImportError:
            print("  [WARN] data_loader not found — stats will use defaults")
            df = pd.DataFrame()

    # ── North star ─────────────────────────────────────────────
    if north_star is None:
        ns_path = os.path.join(output_dir or ".", "company_north_star.json")
        if os.path.exists(ns_path):
            with open(ns_path, encoding="utf-8") as f:
                north_star = json.load(f)
        else:
            north_star = {
                "inferred_north_star": {
                    "metric_name": "Monthly Retention",
                    "definition":  "Users who complete an exercise within the month out of all users who converted from trial.",
                }
            }

    # ── Load feature_goal_map and tone_matrix from disk if not passed ──
    if feature_goal_map is None:
        feature_goal_map = _load_feature_goal_map(output_dir)
    if tone_matrix is None:
        tone_matrix = _load_tone_matrix(output_dir)

    # Build lookup indexes
    tone_index = _index_tone_matrix(tone_matrix)

    # ── Load segments ──────────────────────────────────────────
    if user_segments_df is None:
        seg_path = os.path.join(output_dir or ".", "user_segments.csv")
        if os.path.exists(seg_path):
            user_segments_df = pd.read_csv(seg_path)
            print(f"  Loaded {len(user_segments_df)} rows from {seg_path}")
        else:
            try:
                from segmentation_engine import gen_user_segments
                user_segments_df, _ = gen_user_segments(df, output_dir)
            except ImportError:
                raise FileNotFoundError(
                    "user_segments.csv not found and segmentation_engine unavailable."
                )

    # ── Deduplicate to segment × lifecycle combos ──────────────
    prop_col = "dominant_propensity" if "dominant_propensity" in user_segments_df.columns else None

    base_cols = ["segment_id", "segment_name", "lifecycle_stage"]
    combos_base = (
        user_segments_df[base_cols]
        .drop_duplicates()
        .sort_values(["lifecycle_stage", "segment_id"])
        .reset_index(drop=True)
    )

    if prop_col:
        dominant = (
            user_segments_df
            .groupby(["segment_id", "lifecycle_stage"])[prop_col]
            .agg(lambda x: x.value_counts().idxmax())
            .reset_index()
            .rename(columns={prop_col: "dominant_propensity"})
        )
        combos = combos_base.merge(dominant, on=["segment_id", "lifecycle_stage"], how="left")
    else:
        combos = combos_base.copy()
        combos["dominant_propensity"] = "unknown"

    kb_text = load_kb()
    rows    = []
    total_combos = len(combos)
    total_phases = sum(len(LIFECYCLE_PHASE_MAP.get(row["lifecycle_stage"], [])) for _, row in combos.iterrows())

    print(f"  {total_combos} segment × lifecycle combinations → {total_phases} segment × phase rows\n")

    call_num = 0
    for _, combo in combos.iterrows():
        sid        = combo["segment_id"]
        sname      = combo["segment_name"]
        lifecycle  = combo["lifecycle_stage"]
        propensity = combo.get("dominant_propensity", "unknown")

        phases = LIFECYCLE_PHASE_MAP.get(lifecycle, [])
        if not phases:
            print(f"  [SKIP] No phases defined for lifecycle '{lifecycle}'")
            continue

        # Derive drives and nudges from the loaded artifacts for this lifecycle
        drives      = _drives_for_lifecycle(tone_index, lifecycle)
        feat_nudges = _derive_feature_nudges(feature_goal_map, lifecycle)

        # ── Compute segment stats from behavioral data ─────────
        if not df.empty and "user_id" in df.columns and "user_id" in user_segments_df.columns:
            seg_user_ids = user_segments_df[user_segments_df["segment_id"] == sid]["user_id"]
            seg_df = df[df["user_id"].isin(seg_user_ids)]
        elif not df.empty and "lifecycle_stage" in df.columns:
            seg_df = df[df["lifecycle_stage"] == lifecycle]
        else:
            seg_df = pd.DataFrame()

        def _mean(col, default):
            return round(seg_df[col].mean(), 3) if col in seg_df.columns and not seg_df.empty else default

        stats = {
            "avg_activeness":   _mean("activeness_score",      0.5),
            "avg_churn_risk":   _mean("churn_risk_score",      0.3),
            "avg_motivation":   _mean("motivation_score",      0.5),
            "avg_exercises":    _mean("exercises_completed_7d", 5),
            "avg_sessions":     _mean("sessions_last_7d",      3),
            "avg_notif_open":   _mean("notif_open_rate_30d",   0.4),
            "avg_streak":       _mean("streak_current",        2),
            "avg_coins":        _mean("coins_balance",         50),
        }

        for phase_key in phases:
            call_num += 1
            # Merge the static scaffold with runtime-derived drives + nudges
            phase_cfg = {
                **PHASE_CONFIG[phase_key],
                "octolysis_drives": drives if drives else PHASE_CONFIG[phase_key]["octolysis_drives"],
                "key_nudges":       feat_nudges,
            }

            print(f"  [{call_num}/{total_phases}] {sid} | {phase_cfg['phase_name']} ({phase_cfg['day_range']})")

            row = _build_phase_goal(
                segment_id=sid,
                segment_name=sname,
                dominant_propensity=propensity,
                phase_key=phase_key,
                phase_cfg=phase_cfg,
                stats=stats,
                north_star=north_star,
                kb_text=kb_text,
            )
            rows.append(row)

    goals_df = pd.DataFrame(rows)

    # ── Column ordering ────────────────────────────────────────
    col_order = [
        "segment_id", "segment_name", "dominant_propensity",
        "lifecycle_stage", "phase_number", "phase_name", "day_range",
        "primary_goal", "sub_goal_1", "sub_goal_2", "sub_goal_3",
    ]
    goals_df = goals_df[[c for c in col_order if c in goals_df.columns]]

    save_csv(goals_df, "segment_goals.csv", output_dir)
    print(f"\n  [goals] segment_goals.csv: {len(goals_df)} rows ({total_combos} segments × up to 11 phases)")
    return goals_df


# ── Standalone runner ─────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Goal Builder — 11-phase segment goal generator")
    parser.add_argument("--segments",        default="user_segments.csv",           help="Path to user_segments.csv")
    parser.add_argument("--behavioral",      default="user_behavioral_data.csv",    help="Path to behavioral CSV")
    parser.add_argument("--north-star",      default="company_north_star.json",     help="Path to north star JSON")
    parser.add_argument("--feature-map",     default="feature_goal_map.json",       help="Path to feature_goal_map.json")
    parser.add_argument("--tone-matrix",     default="allowed_tone_hook_matrix.json", help="Path to tone_hook_matrix JSON")
    parser.add_argument("--output-dir",      default=".",                           help="Output directory")
    args = parser.parse_args()

    seg_df = pd.read_csv(args.segments) if os.path.exists(args.segments) else None
    beh_df = pd.read_csv(args.behavioral) if os.path.exists(args.behavioral) else None

    ns = None
    if os.path.exists(args.north_star):
        with open(args.north_star, encoding="utf-8") as f:
            ns = json.load(f)

    fgm = None
    if os.path.exists(args.feature_map):
        with open(args.feature_map, encoding="utf-8") as f:
            fgm = json.load(f)

    tm = None
    if os.path.exists(args.tone_matrix):
        with open(args.tone_matrix, encoding="utf-8") as f:
            tm = json.load(f)

    os.makedirs(args.output_dir, exist_ok=True)
    goals = gen_segment_goals(
        user_segments_df=seg_df,
        df=beh_df,
        north_star=ns,
        output_dir=args.output_dir,
        feature_goal_map=fgm,
        tone_matrix=tm,
    )
    print(goals[["segment_id", "phase_name", "primary_goal"]].to_string(index=False))
