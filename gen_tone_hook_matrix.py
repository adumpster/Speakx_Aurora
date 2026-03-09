# gen_tone_hook_matrix.py
# Generates: allowed_tone_hook_matrix.json
#
# Output format:
# {
#   "allowed_tones":    ["Motivational", "Encouraging", ...],   ← flat list, KB-extracted
#   "disallowed_tones": ["Shaming", "Aggressive sales pressure", ...],
#   "hook_taxonomy": [
#     {
#       "core_drive":      "Epic Meaning",
#       "application":     "one sentence from KB context",
#       "example_phrases": ["English hook", "Hindi hook"]
#     }, ...
#   ],
#   "matrix": [ { per-lifecycle-stage entry } ],
#   ...
# }
#
# LLM backend: local Ollama (via llm.py wrapper).
# Tones MUST be extracted from KB's Ethical Communication Guidelines — not invented.
# ─────────────────────────────────────────────────────────────

from llm         import llm, safe_parse_json, save_json
from data_loader import load_and_profile, DataProfile
from kb_loader   import build_context
from config      import OCTOLYSIS_DRIVES, LIFECYCLE_STAGES

import datetime


# ── Two-pass architecture ─────────────────────────────────────
# Pass 1: Extract global allowed/disallowed tones from KB
# Pass 2: Build per-lifecycle matrix + hook_taxonomy using those tones
# Splitting into two focused prompts improves Ollama reliability over
# one massive prompt, and lets us validate each pass independently.
# ─────────────────────────────────────────────────────────────


def _pass1_extract_tones(context: str) -> dict:
    """
    Pass 1 — Extract global allowed and disallowed tones directly from the
    KB's Ethical Communication Guidelines section.
    Returns: { "allowed_tones": [...], "disallowed_tones": [...] }
    """
    raw = llm(
        system=(
            "You are a communication policy analyst. "
            "Your ONLY job is to read the Knowledge Bank provided and extract "
            "the allowed and disallowed communication tones exactly as stated. "
            "Do NOT invent, paraphrase loosely, or add tones not in the document. "
            "Output ONLY valid JSON — no markdown, no explanation."
        ),
        prompt=f"""
{context}

TASK:
Read the 'Ethical Communication Guidelines' section of the Knowledge Bank above.
Extract EVERY allowed tone and EVERY disallowed tone that is explicitly stated.

Format each tone as a short title-cased label (e.g. "Motivational", "Friendly", "Shaming").

Return ONLY this JSON:
{{
  "allowed_tones":    ["<tone>", "<tone>", ...],
  "disallowed_tones": ["<tone>", "<tone>", ...]
}}""",
    )

    result = safe_parse_json(raw, fallback={
        "allowed_tones":    ["Motivational", "Encouraging", "Celebratory", "Urgent (mild)", "Friendly", "Informative"],
        "disallowed_tones": ["Shaming", "Aggressive sales pressure", "Fear-mongering", "Condescending"],
    })

    # Ensure both keys exist
    if "allowed_tones" not in result or not result["allowed_tones"]:
        result["allowed_tones"] = ["Motivational", "Encouraging", "Celebratory", "Urgent (mild)", "Friendly", "Informative"]
    if "disallowed_tones" not in result or not result["disallowed_tones"]:
        result["disallowed_tones"] = ["Shaming", "Aggressive sales pressure", "Fear-mongering", "Condescending"]

    return result


def _pass2_build_taxonomy_and_matrix(
    context: str,
    allowed_tones: list,
    disallowed_tones: list,
    drives_block: str,
    stages_block: str,
) -> dict:
    """
    Pass 2 — Using the KB context and the already-extracted tones, build:
      - hook_taxonomy  : one entry per Octolysis drive, grounded in KB
      - matrix         : per-lifecycle-stage drive selection + tone rationale
    """
    allowed_str    = ", ".join(f'"{t}"' for t in allowed_tones)
    disallowed_str = ", ".join(f'"{t}"' for t in disallowed_tones)

    raw = llm(
        system=(
            "You are a behavioral product communication strategist specialising in "
            "Octolysis gamification framework. Use the Knowledge Bank to ground every "
            "application description and example phrase in real product context. "
            "Output ONLY valid JSON — no markdown, no explanation."
        ),
        prompt=f"""
{context}

Octolysis 8 Core Drives (use these exact names):
{drives_block}

Lifecycle stages and their primary goals:
{stages_block}

Already-extracted tones from KB Ethical Communication Guidelines:
  Allowed    : {allowed_str}
  Disallowed : {disallowed_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK A — hook_taxonomy
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For EACH of the 8 Octolysis drives generate:
  - core_drive     : exact drive name from the list above
  - application    : one sentence grounded in the KB (product features, user goals, journey)
  - example_phrases: exactly 2 items — [0] natural English, [1] conversational Hindi (use
                     Hinglish style: mix Hindi script + Roman where natural)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK B — per-lifecycle matrix
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For EACH lifecycle stage choose from the ALREADY-EXTRACTED tones above:
  - allowed_tones    : subset of the allowed list most appropriate for this stage
  - disallowed_tones : subset of the disallowed list most relevant to warn against
  - primary_drives   : top 3 Octolysis drives for this stage
  - secondary_drives : 2 supporting drives
  - hook_intensity   : "high" | "medium" | "low"
  - tone_rationale   : 1-2 sentences referencing KB guidelines + why for this stage

Return ONLY this JSON:
{{
  "hook_taxonomy": [
    {{
      "core_drive":      "Epic Meaning",
      "application":     "<one KB-grounded sentence>",
      "example_phrases": ["<English>", "<Hindi>"]
    }},
    {{
      "core_drive":      "Accomplishment",
      "application":     "<one KB-grounded sentence>",
      "example_phrases": ["<English>", "<Hindi>"]
    }},
    {{
      "core_drive":      "Empowerment",
      "application":     "<one KB-grounded sentence>",
      "example_phrases": ["<English>", "<Hindi>"]
    }},
    {{
      "core_drive":      "Ownership",
      "application":     "<one KB-grounded sentence>",
      "example_phrases": ["<English>", "<Hindi>"]
    }},
    {{
      "core_drive":      "Social Influence",
      "application":     "<one KB-grounded sentence>",
      "example_phrases": ["<English>", "<Hindi>"]
    }},
    {{
      "core_drive":      "Scarcity",
      "application":     "<one KB-grounded sentence>",
      "example_phrases": ["<English>", "<Hindi>"]
    }},
    {{
      "core_drive":      "Unpredictability",
      "application":     "<one KB-grounded sentence>",
      "example_phrases": ["<English>", "<Hindi>"]
    }},
    {{
      "core_drive":      "Loss Avoidance",
      "application":     "<one KB-grounded sentence>",
      "example_phrases": ["<English>", "<Hindi>"]
    }}
  ],
  "matrix": [
    {{
      "lifecycle_stage":  "<stage>",
      "allowed_tones":    ["<from extracted allowed list>"],
      "disallowed_tones": ["<from extracted disallowed list>"],
      "primary_drives":   ["<drive>", "<drive>", "<drive>"],
      "secondary_drives": ["<drive>", "<drive>"],
      "hook_intensity":   "<high|medium|low>",
      "tone_rationale":   "<KB-grounded rationale for this stage>"
    }}
  ]
}}""",
    )

    fallback = {
        "hook_taxonomy": _default_hook_taxonomy(),
        "matrix":        [_default_stage_entry(s, allowed_tones, disallowed_tones)
                          for s in LIFECYCLE_STAGES],
    }

    result = safe_parse_json(raw, fallback=fallback)

    # ── Validate and patch ────────────────────────────────────
    if not isinstance(result, dict):
        result = fallback

    # Ensure all 8 drives present in taxonomy
    if "hook_taxonomy" not in result or len(result.get("hook_taxonomy", [])) < 8:
        result["hook_taxonomy"] = _default_hook_taxonomy()

    # Ensure all lifecycle stages present in matrix
    result.setdefault("matrix", [])
    existing = {e.get("lifecycle_stage") for e in result["matrix"]}
    for stage in LIFECYCLE_STAGES:
        if stage not in existing:
            result["matrix"].append(
                _default_stage_entry(stage, allowed_tones, disallowed_tones)
            )

    return result


# ── Public entry point ────────────────────────────────────────

def gen_tone_hook_matrix(profile: DataProfile = None, output_dir: str = None) -> dict:
    print("\n[3/5] Generating: allowed_tone_hook_matrix.json")

    if profile is None:
        profile = load_and_profile()

    context = build_context(profile.summary)

    drives_block = "\n".join(
        f'  {d["id"]}. {d["name"]}: "{d["hook"]}"'
        for d in OCTOLYSIS_DRIVES
    )
    stages_block = "\n".join(
        f'  {s}: {v["primary_goal"]}'
        for s, v in LIFECYCLE_STAGES.items()
    )

    # ── Pass 1: extract tones from KB ────────────────────────
    print("  [Pass 1/2] Extracting tones from KB Ethical Communication Guidelines...")
    tones = _pass1_extract_tones(context)
    allowed_tones    = tones["allowed_tones"]
    disallowed_tones = tones["disallowed_tones"]
    print(f"    → {len(allowed_tones)} allowed | {len(disallowed_tones)} disallowed")

    # ── Pass 2: taxonomy + matrix ─────────────────────────────
    print("  [Pass 2/2] Building hook taxonomy and per-stage matrix...")
    payload = _pass2_build_taxonomy_and_matrix(
        context, allowed_tones, disallowed_tones, drives_block, stages_block
    )

    # ── Assemble final output ─────────────────────────────────
    data = {
        "allowed_tones":    allowed_tones,        # flat global list (KB-extracted)
        "disallowed_tones": disallowed_tones,      # flat global list (KB-extracted)
        "hook_taxonomy":    payload["hook_taxonomy"],
        "matrix":           payload["matrix"],
        "source":           "KB Ethical Communication Guidelines",
        "bilingual_note":   "All messages must be available in Hindi and English",
        "generated_at":     datetime.date.today().isoformat(),
        "iteration":        0,
    }

    save_json(data, "allowed_tone_hook_matrix.json", output_dir)
    print("  ✓ Saved → allowed_tone_hook_matrix.json")
    return data


# ── Fallback defaults ─────────────────────────────────────────

def _default_hook_taxonomy() -> list:
    return [
        {
            "core_drive":      "Epic Meaning",
            "application":     "Connect daily English practice to transformative career and life outcomes for Tier 2/3 users.",
            "example_phrases": [
                "Join 1M+ learners transforming their careers with SpeakX!",
                "Apni zindagi badlo — SpeakX ke saath aaj se shuru karo!",
            ],
        },
        {
            "core_drive":      "Accomplishment",
            "application":     "Celebrate streaks, completed lessons, and fluency milestones to reinforce daily habit.",
            "example_phrases": [
                "You completed 5 lessons! Keep the momentum going.",
                "Aapne 5 lessons kiye — kya baat hai! Aage badho!",
            ],
        },
        {
            "core_drive":      "Empowerment",
            "application":     "Let users choose their own speaking topics and practice scenarios to build autonomy.",
            "example_phrases": [
                "Choose your learning path today — job interview, confidence, or daily conversation.",
                "Aaj kya sikhna chahte ho? Aap hi decide karo!",
            ],
        },
        {
            "core_drive":      "Ownership",
            "application":     "Make earned coins, streaks, and progress feel personally owned and worth protecting.",
            "example_phrases": [
                "Your 50 coins are waiting to be spent — don't let them go to waste!",
                "Tumhare 50 coins pade hain — inhe use karo!",
            ],
        },
        {
            "core_drive":      "Social Influence",
            "application":     "Surface leaderboard rankings and friend activity to trigger competitive social proof.",
            "example_phrases": [
                "3 friends joined this week — invite more and climb the leaderboard!",
                "Tere 3 dost aa gaye — tu bhi aage badh aur rank badhao!",
            ],
        },
        {
            "core_drive":      "Scarcity",
            "application":     "Highlight limited trial days and expiring offers to create genuine urgency.",
            "example_phrases": [
                "Only 2 days left in your trial — upgrade now to keep your streak!",
                "Sirf 2 din bache hain trial mein — abhi upgrade karo!",
            ],
        },
        {
            "core_drive":      "Unpredictability",
            "application":     "Surprise rewards and mystery challenges in Sia conversations keep users coming back.",
            "example_phrases": [
                "Surprise reward inside today's lesson — open to find out!",
                "Aaj ke lesson mein ek surprise hai — dekho kya milta hai!",
            ],
        },
        {
            "core_drive":      "Loss Avoidance",
            "application":     "Protect streak anxiety and rank loss to drive daily check-ins and re-engagement.",
            "example_phrases": [
                "Your 7-day streak is at risk — practice now to save it!",
                "Tera 7-din ka streak toot sakta hai — abhi practice karo!",
            ],
        },
    ]


def _default_stage_entry(stage: str, allowed: list = None, disallowed: list = None) -> dict:
    """Sensible per-stage defaults that subset the globally extracted tones."""

    # Stage-specific subsets drawn from the KB-extracted global lists
    stage_tone_map = {
        "trial": {
            "allowed_tones":    ["Encouraging", "Friendly", "Informative", "Motivational"],
            "disallowed_tones": ["Shaming", "Aggressive sales pressure", "Fear-mongering"],
            "primary_drives":   ["Scarcity", "Empowerment", "Accomplishment"],
            "secondary_drives": ["Epic Meaning", "Unpredictability"],
            "hook_intensity":   "high",
            "tone_rationale":   (
                "Trial users need activation energy and value discovery — "
                "KB guidelines prohibit pressure-heavy tactics; warm encouragement converts best."
            ),
        },
        "paid": {
            "allowed_tones":    ["Motivational", "Celebratory", "Friendly", "Informative"],
            "disallowed_tones": ["Shaming", "Condescending", "Aggressive sales pressure"],
            "primary_drives":   ["Accomplishment", "Loss Avoidance", "Social Influence"],
            "secondary_drives": ["Ownership", "Unpredictability"],
            "hook_intensity":   "medium",
            "tone_rationale":   (
                "Paid users respond to progress affirmation and streak protection — "
                "celebratory and motivational tones reinforce investment without pressure."
            ),
        },
        "churned": {
            "allowed_tones":    ["Encouraging", "Friendly", "Informative"],
            "disallowed_tones": ["Shaming", "Aggressive sales pressure", "Condescending"],
            "primary_drives":   ["Epic Meaning", "Loss Avoidance", "Empowerment"],
            "secondary_drives": ["Unpredictability", "Accomplishment"],
            "hook_intensity":   "low",
            "tone_rationale":   (
                "Churned users need a soft, nostalgic re-entry — "
                "KB bans shaming and pressure; empathetic value reminders work best."
            ),
        },
        "inactive": {
            "allowed_tones":    ["Motivational", "Urgent (mild)", "Friendly", "Encouraging"],
            "disallowed_tones": ["Shaming", "Fear-mongering", "Condescending"],
            "primary_drives":   ["Loss Avoidance", "Epic Meaning", "Unpredictability"],
            "secondary_drives": ["Social Influence", "Scarcity"],
            "hook_intensity":   "medium",
            "tone_rationale":   (
                "Inactive users respond to streak-loss warnings and FOMO — "
                "mild urgency is KB-permitted; shaming and fear-mongering are not."
            ),
        },
    }

    defaults = stage_tone_map.get(stage, {
        "allowed_tones":    allowed or ["Informative", "Friendly"],
        "disallowed_tones": disallowed or ["Shaming", "Aggressive sales pressure"],
        "primary_drives":   ["Accomplishment"],
        "secondary_drives": ["Epic Meaning"],
        "hook_intensity":   "medium",
        "tone_rationale":   "Default moderate tone per KB guidelines.",
    })

    return {"lifecycle_stage": stage, **defaults}