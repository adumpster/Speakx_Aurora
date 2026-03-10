# message_template_gen.py
# ─────────────────────────────────────────────────────────────
# Generates: message_templates.csv
#
# Creates exactly 5 templates per Segment × Phase × Theme.
# Each template has bilingual content (English + Hindi/Hinglish),
# a tone, an Octolysis hook type, a CTA, and a feature reference.
#
# Architecture:
#   - Phase-aware: operates on segment × phase from comm_themes + goals
#   - feature_ref resolved from feature_goal_map.json (domain-agnostic)
#   - Transcreation prompt: Hindi is NOT a literal translation — same
#     psychological urgency in natural conversational Hindi
#   - Concurrent via concurrent.futures.ThreadPoolExecutor (max 2 threads)
#   - Retry logic: up to 3 attempts per combination before fallback
#   - No LangChain — pure llm.py + safe_parse_json
#
# Inputs (all auto-loaded if not passed):
#   communication_themes.csv  → segment × phase themes + tones
#   segment_goals.csv         → primary_goal per segment × phase
#   feature_goal_map.json     → goal → feature reference mapping
#
# Output:
#   message_templates.csv     → 5 rows per segment × phase
# ─────────────────────────────────────────────────────────────

import os
import json
import re
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from llm         import llm, safe_parse_json, save_csv
from data_loader import load_data
from kb_loader   import load_kb
from config      import OCTOLYSIS_DRIVES

TEMPLATES_PER_COMBO = 5
MAX_RETRIES         = 3
MAX_WORKERS         = 2

# ── Message Format Archetypes (one per template slot) ─────────
# Each archetype defines a distinct structural pattern so the 5
# templates for the same Segment × Phase are stylistically varied.
MESSAGE_FORMATS = [
    {
        "id":          "direct_cta",
        "name":        "Direct CTA",
        "description": "Imperative, action-first. Lead with a strong verb. No frills.",
        "example":     "Title: 'Start Today's Session' | Body: 'Three minutes is all it takes. Open now and keep your streak alive.'",
    },
    {
        "id":          "question_hook",
        "name":        "Question Hook",
        "description": "Open with a short rhetorical question that creates cognitive engagement.",
        "example":     "Title: 'Ready to beat yesterday?' | Body: 'Your last score was 72. Can you top it in 5 minutes today?'",
    },
    {
        "id":          "social_proof",
        "name":        "Social Proof",
        "description": "Reference peers, ranks, or aggregate stats to trigger social motivation.",
        "example":     "Title: '1,400 learners practiced today' | Body: 'Don't fall behind — your peers are moving forward. Join them now.'",
    },
    {
        "id":          "insight_tip",
        "name":        "Insight / Tip",
        "description": "Lead with a surprising fact, stat, or micro-tip relevant to the goal.",
        "example":     "Title: 'Tip: 10 min daily beats 2 hr weekly' | Body: 'Consistency builds fluency. One short session now keeps progress compounding.'",
    },
    {
        "id":          "challenge",
        "name":        "Challenge / Gamified",
        "description": "Frame the action as a personal challenge, game, or streak milestone.",
        "example":     "Title: 'Day 5 Challenge Unlocked' | Body: 'You're on a roll — tackle today's challenge to unlock your next badge.'",
    },
]


def _formats_reference() -> str:
    lines = []
    for i, f in enumerate(MESSAGE_FORMATS, 1):
        lines.append(
            f'  Format {i} — {f["name"]} ({f["id"]})\n'
            f'    Rule: {f["description"]}\n'
            f'    Example: {f["example"]}'
        )
    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────

def _drives_reference() -> str:
    return "\n".join(
        f'  {d["id"]}. {d["name"]}: "{d["hook"]}"'
        for d in OCTOLYSIS_DRIVES
    )


def _load_feature_map(feature_goal_map_path: str = "feature_goal_map.json") -> dict:
    """
    Load goal → feature label mapping from feature_goal_map.json.
    Returns a plain dict {goal_keyword: feature_label}.
    Falls back to an empty dict — feature_ref will default to 'general'.
    """
    if not os.path.exists(feature_goal_map_path):
        return {}
    with open(feature_goal_map_path, encoding="utf-8") as f:
        raw = json.load(f)

    # feature_goal_map.json has structure: {"feature_goal_map": [{feature, primary_goal, ...}]}
    # Build a reverse lookup: primary_goal substring → feature label
    mapping = {}
    entries = raw if isinstance(raw, list) else raw.get("feature_goal_map", raw)
    if isinstance(entries, list):
        for entry in entries:
            feature = entry.get("feature", entry.get("feature_id", "general"))
            goal    = entry.get("primary_goal", "")
            if goal:
                # Use first 40 chars of goal as a loose key for matching
                mapping[goal[:40].lower()] = feature
    elif isinstance(entries, dict):
        mapping = entries
    return mapping


def _resolve_feature_ref(primary_goal: str, feature_map: dict) -> str:
    """
    Match primary_goal against feature_map keys via substring search.
    Returns the feature label or 'general' if no match.
    """
    goal_lower = primary_goal.lower()
    for key, label in feature_map.items():
        if key in goal_lower or goal_lower[:40] in key:
            return label
    return "general"


def _unwrap_list(parsed) -> list:
    """Unwrap LLM output that may be a dict wrapping a list."""
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ["templates", "variations", "messages", "items", "data", "notifications"]:
            if key in parsed and isinstance(parsed[key], list):
                return parsed[key]
    return []


def _make_template_id(segment_id: str, phase_name: str, idx: int) -> str:
    safe_phase = re.sub(r"[^A-Za-z0-9]", "_", str(phase_name)).upper()
    return f"TPL_{segment_id}_{safe_phase}_{idx:02d}"


# ── Fallback row ──────────────────────────────────────────────

def _fallback_row(
    segment_id:    str,
    segment_name:  str,
    lifecycle:     str,
    phase_number:  int,
    phase_name:    str,
    day_range:     str,
    primary_goal:  str,
    primary_theme: str,
    tone:          str,
    feature_ref:   str,
    idx:           int,
) -> dict:
    slot_idx = max(0, min(idx - 1, len(MESSAGE_FORMATS) - 1))
    return {
        "template_id":   _make_template_id(segment_id, phase_name, idx),
        "segment_id":    segment_id,
        "segment_name":  segment_name,
        "lifecycle_stage": lifecycle,
        "phase_number":  phase_number,
        "phase_name":    phase_name,
        "day_range":     day_range,
        "primary_goal":  primary_goal,
        "theme":         primary_theme,
        "tone":          tone,
        "title_en":      "Keep going — your progress awaits!",
        "body_en":       "You're making great strides. One session today keeps your streak alive.",
        "title_hi":      "Chalo aage badho!",
        "body_hi":       "Tumhari mehnat rang la rahi hai. Aaj ek session karo, streak bachao.",
        "hook_type":     primary_theme,
        "format_type":   MESSAGE_FORMATS[slot_idx]["id"],
        "cta_en":        "Start Now",
        "cta_hi":        "Abhi Shuru Karo",
        "feature_ref":   feature_ref,
        "iteration":     0,
    }


# ── Core LLM call with retry ──────────────────────────────────

def _gen_templates_for_combo(
    segment_id:    str,
    segment_name:  str,
    lifecycle:     str,
    phase_number:  int,
    phase_name:    str,
    day_range:     str,
    primary_goal:  str,
    sub_goal_1:    str,
    primary_theme: str,
    secondary_theme: str,
    tone:          str,
    feature_ref:   str,
    combo_index:   int,
) -> list[dict]:
    """
    One llm() call (up to MAX_RETRIES) → exactly 5 template rows.
    Hindi is transcreated — same psychological urgency, natural conversational tone.
    """
    drives_block  = _drives_reference()
    formats_block = _formats_reference()
    kb_context    = load_kb()

    # Pre-assign one format to each of the 5 template slots
    slot_formats = "\n".join(
        f'  Template {i+1}: format_type = "{MESSAGE_FORMATS[i]["id"]}"  ({MESSAGE_FORMATS[i]["name"]})'
        for i in range(TEMPLATES_PER_COMBO)
    )

    prompt_text = f"""
APP KNOWLEDGE BANK:
{kb_context}

=== COMBINATION CONTEXT ===
Segment        : {segment_name} (id: {segment_id})
Lifecycle      : {lifecycle}
Phase          : {phase_name} ({day_range})
Primary Goal   : {primary_goal}
Sub Goal       : {sub_goal_1}
Primary Theme  : {primary_theme}
Secondary Theme: {secondary_theme}
Tone           : {tone}
Feature Focus  : {feature_ref}

Octolysis 8 Core Drives reference:
{drives_block}

Message Format Archetypes:
{formats_block}

=== SLOT ASSIGNMENTS ===
Each template MUST use BOTH an assigned format AND a distinct Octolysis hook:
{slot_formats}

=== TASK ===
Write EXACTLY 5 distinct push notification templates for this segment × phase.

RULES:
1. Each of the 5 must use a DIFFERENT Octolysis hook_type from the drives above.
2. Each template MUST match its assigned format_type slot above — the structure and
   opening style must clearly reflect that format archetype.
3. English: short, punchy, action-oriented. Title ≤ 8 words. Body ≤ 20 words. CTA ≤ 4 words.
4. Hindi/Hinglish: TRANSCREATE — do NOT translate literally. Keep identical psychological
   urgency but use natural, conversational Hindi that an Indian professional/student
   would actually respond to. Roman+Devanagari Hinglish is encouraged.
5. No emojis. No generic filler. Every line must earn its place.
6. Reflect the phase goal and tone in every template.

Return ONLY a valid JSON array of exactly 5 objects — no wrapper, no explanation:
[
  {{
    "title_en":    "<English title — max 8 words>",
    "body_en":     "<English body — max 20 words>",
    "cta_en":      "<English CTA — max 4 words>",
    "title_hi":    "<Transcreated Hindi/Hinglish title>",
    "body_hi":     "<Transcreated Hindi/Hinglish body>",
    "cta_hi":      "<Hindi CTA — max 4 words>",
    "hook_type":   "<exact Octolysis drive name>",
    "format_type": "<assigned format_type id for this slot>",
    "feature_ref": "<{feature_ref} or most relevant feature>"
  }}
]"""

    valid_themes = {d["name"] for d in OCTOLYSIS_DRIVES}

    for attempt in range(1, MAX_RETRIES + 1):
        raw    = llm(system="You are a bilingual push notification copywriter. Output ONLY valid JSON.", prompt=prompt_text)
        parsed = safe_parse_json(raw, fallback=[])
        items  = _unwrap_list(parsed)

        if len(items) >= TEMPLATES_PER_COMBO:
            break
        if attempt < MAX_RETRIES:
            print(f"    [retry {attempt}/{MAX_RETRIES}] got {len(items)} templates, need {TEMPLATES_PER_COMBO}")

    valid_format_ids = {f["id"] for f in MESSAGE_FORMATS}

    rows = []
    for t_idx, t in enumerate(items[:TEMPLATES_PER_COMBO], 1):
        if not isinstance(t, dict):
            continue
        hook = t.get("hook_type", primary_theme)
        if hook not in valid_themes:
            hook = primary_theme
        # Use LLM-returned format_type if valid; otherwise fall back to the slot assignment
        fmt = t.get("format_type", MESSAGE_FORMATS[t_idx - 1]["id"])
        if fmt not in valid_format_ids:
            fmt = MESSAGE_FORMATS[t_idx - 1]["id"]
        rows.append({
            "template_id":     _make_template_id(segment_id, phase_name, t_idx),
            "segment_id":      segment_id,
            "segment_name":    segment_name,
            "lifecycle_stage": lifecycle,
            "phase_number":    phase_number,
            "phase_name":      phase_name,
            "day_range":       day_range,
            "primary_goal":    primary_goal,
            "theme":           primary_theme,
            "tone":            tone,
            "title_en":        t.get("title_en", ""),
            "body_en":         t.get("body_en", ""),
            "cta_en":          t.get("cta_en", "Start Now"),
            "title_hi":        t.get("title_hi", ""),
            "body_hi":         t.get("body_hi", ""),
            "cta_hi":          t.get("cta_hi", "Abhi Shuru Karo"),
            "hook_type":       hook,
            "format_type":     fmt,
            "feature_ref":     t.get("feature_ref", feature_ref),
            "iteration":       0,
        })

    # Pad to exactly 5 with fallback rows if LLM fell short after retries
    while len(rows) < TEMPLATES_PER_COMBO:
        rows.append(_fallback_row(
            segment_id, segment_name, lifecycle, phase_number,
            phase_name, day_range, primary_goal, primary_theme,
            tone, feature_ref, len(rows) + 1,
        ))

    return rows


# ── ThreadPool worker ─────────────────────────────────────────

def _worker(idx: int, job: dict) -> tuple[int, list[dict]]:
    """Wrapper so ThreadPoolExecutor can call _gen_templates_for_combo."""
    templates = _gen_templates_for_combo(**{k: v for k, v in job.items() if k != "combo_index"},
                                         combo_index=job["combo_index"])
    return idx, templates


# ── Main entry point ──────────────────────────────────────────

def gen_message_templates(
    themes_df:        Optional[pd.DataFrame] = None,
    goals_df:         Optional[pd.DataFrame] = None,
    user_segments_df: Optional[pd.DataFrame] = None,
    df:               Optional[pd.DataFrame] = None,
    feature_goal_map: Optional[dict]         = None,
    output_dir:       Optional[str]          = None,
    max_workers:      int                    = MAX_WORKERS,
) -> pd.DataFrame:
    """
    Build message_templates.csv — 5 templates per Segment × Phase.

    Args:
        themes_df        : output of gen_communication_themes (comm_themes.csv)
        goals_df         : output of gen_segment_goals (segment_goals.csv)
        user_segments_df : output of gen_user_segments (user_segments.csv)
        df               : raw behavioral DataFrame
        feature_goal_map : loaded feature_goal_map.json (auto-loaded if None)
        output_dir       : output directory override
        max_workers      : concurrent Ollama threads (default 2)
    """
    print("\n[Task2-2/4] Generating: message_templates.csv")

    if df is None:
        df = load_data()

    # ── Load communication themes ─────────────────────────────
    if themes_df is None:
        themes_path = "communication_themes.csv"
        if os.path.exists(themes_path):
            themes_df = pd.read_csv(themes_path)
        else:
            from comm_themes import gen_communication_themes
            themes_df = gen_communication_themes(
                user_segments_df=user_segments_df, df=df, output_dir=output_dir
            )

    # ── Load segment goals ────────────────────────────────────
    if goals_df is None:
        goals_path = "segment_goals.csv"
        if os.path.exists(goals_path):
            goals_df = pd.read_csv(goals_path)

    # ── Load feature map ──────────────────────────────────────
    if feature_goal_map is None:
        feature_goal_map = _load_feature_map("feature_goal_map.json")

    # ── Merge primary_goal + sub_goal_1 from goals if available ──
    # comm_themes already has primary_goal, but goals has richer sub-goals
    if goals_df is not None:
        goal_cols = ["segment_id", "phase_name", "primary_goal", "sub_goal_1"]
        available = [c for c in goal_cols if c in goals_df.columns]
        goal_lookup = goals_df[available].drop_duplicates(subset=["segment_id", "phase_name"])

        merge_on = ["segment_id"]
        if "phase_name" in themes_df.columns and "phase_name" in goal_lookup.columns:
            merge_on.append("phase_name")

        themes_df = themes_df.merge(goal_lookup, on=merge_on, how="left", suffixes=("", "_goal"))

        # Prefer goal file's primary_goal over themes if both exist
        if "primary_goal_goal" in themes_df.columns:
            themes_df["primary_goal"] = themes_df["primary_goal_goal"].fillna(
                themes_df.get("primary_goal", "Drive daily engagement")
            )
            themes_df.drop(columns=["primary_goal_goal"], inplace=True)

    if "primary_goal" not in themes_df.columns:
        themes_df["primary_goal"] = "Drive daily engagement"
    themes_df["primary_goal"] = themes_df["primary_goal"].fillna("Drive daily engagement")

    if "sub_goal_1" not in themes_df.columns:
        themes_df["sub_goal_1"] = ""
    themes_df["sub_goal_1"] = themes_df["sub_goal_1"].fillna("")

    # ── Normalise column names (tone col differs between versions) ─
    if "tone" in themes_df.columns and "tone_preference" not in themes_df.columns:
        themes_df.rename(columns={"tone": "tone_preference"}, inplace=True)
    if "tone_preference" not in themes_df.columns:
        themes_df["tone_preference"] = "Motivational"

    if "secondary_theme" not in themes_df.columns:
        themes_df["secondary_theme"] = themes_df.get("primary_theme", "Accomplishment")

    total = len(themes_df)
    print(f"  {total} segment × phase combinations → {total * TEMPLATES_PER_COMBO} templates total\n")

    # ── Build job list ────────────────────────────────────────
    jobs = []
    for combo_idx, (_, row) in enumerate(themes_df.iterrows(), 1):
        sid        = str(row["segment_id"])
        feature_ref = _resolve_feature_ref(str(row["primary_goal"]), feature_goal_map)
        jobs.append({
            "segment_id":      sid,
            "segment_name":    str(row.get("segment_name", sid)),
            "lifecycle":       str(row.get("lifecycle_stage", "")),
            "phase_number":    int(row.get("phase_number", 0)),
            "phase_name":      str(row.get("phase_name", "")),
            "day_range":       str(row.get("day_range", "")),
            "primary_goal":    str(row["primary_goal"]),
            "sub_goal_1":      str(row["sub_goal_1"]),
            "primary_theme":   str(row.get("primary_theme", "")),
            "secondary_theme": str(row.get("secondary_theme", "")),
            "tone":            str(row["tone_preference"]),
            "feature_ref":     feature_ref,
            "combo_index":     combo_idx,
        })

    # ── Concurrent execution ──────────────────────────────────
    results_map: dict[int, list] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_worker, idx, job): idx for idx, job in enumerate(jobs)}
        completed = 0
        for future in as_completed(futures):
            idx = futures[future]
            job = jobs[idx]
            try:
                _, templates = future.result()
                results_map[idx] = templates
                completed += 1
                print(f"  [{completed}/{total}] ✓ {job['segment_id']} | {job['phase_name']} → {len(templates)} templates")
            except Exception as e:
                print(f"  [!] ✗ {job['segment_id']} | {job['phase_name']} — {e}")
                results_map[idx] = [
                    _fallback_row(
                        job["segment_id"], job["segment_name"], job["lifecycle"],
                        job["phase_number"], job["phase_name"], job["day_range"],
                        job["primary_goal"], job["primary_theme"],
                        job["tone"], job["feature_ref"], i,
                    )
                    for i in range(1, TEMPLATES_PER_COMBO + 1)
                ]

    # Reassemble in original order
    all_rows = []
    for i in range(len(jobs)):
        all_rows.extend(results_map.get(i, []))

    templates_df = pd.DataFrame(all_rows)
    save_csv(templates_df, "message_templates.csv", output_dir)
    return templates_df


# ── Standalone runner ─────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Message Template Generator — phase-aware, bilingual")
    parser.add_argument("--themes",      default="communication_themes.csv", help="comm_themes CSV path")
    parser.add_argument("--goals",       default="segment_goals.csv",        help="segment_goals CSV path")
    parser.add_argument("--segments",    default="user_segments.csv",        help="user_segments CSV path")
    parser.add_argument("--feature-map", default="feature_goal_map.json",   help="feature_goal_map JSON path")
    parser.add_argument("--behavioral",  default="user_behavioral_data.csv", help="behavioral CSV path")
    parser.add_argument("--output-dir",  default=".",                        help="output directory")
    parser.add_argument("--workers",     default=2, type=int,                help="max concurrent Ollama threads")
    args = parser.parse_args()

    themes_df = pd.read_csv(args.themes)   if os.path.exists(args.themes)   else None
    goals_df  = pd.read_csv(args.goals)    if os.path.exists(args.goals)    else None
    seg_df    = pd.read_csv(args.segments) if os.path.exists(args.segments) else None
    beh_df    = pd.read_csv(args.behavioral) if os.path.exists(args.behavioral) else None
    fmap      = None
    if os.path.exists(args.feature_map):
        with open(args.feature_map, encoding="utf-8") as f:
            fmap = json.load(f)

    os.makedirs(args.output_dir, exist_ok=True)

    out = gen_message_templates(
        themes_df        = themes_df,
        goals_df         = goals_df,
        user_segments_df = seg_df,
        df               = beh_df,
        feature_goal_map = fmap,
        output_dir       = args.output_dir,
        max_workers      = args.workers,
    )
    print(f"\n{len(out)} total template rows written.")
    print(out[["template_id", "segment_id", "phase_name", "hook_type", "title_en"]].head(10).to_string(index=False))