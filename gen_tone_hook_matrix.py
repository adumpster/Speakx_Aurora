# gen_tone_hook_matrix.py  (was extract_matrix.py)
# Generates: allowed_tone_hook_matrix.json

from llm         import llm, safe_parse_json, save_json
from data_loader import load_and_profile, DataProfile
from kb_loader   import build_context
from config      import OCTOLYSIS_DRIVES, LIFECYCLE_STAGES


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

    raw = llm(
        system=(
            "You are a communication strategist. "
            "You MUST extract allowed/disallowed tones from the KB's Ethical Communication "
            "Guidelines section — do not invent tones. Output ONLY valid JSON."
        ),
        prompt=f"""
{context}

Octolysis 8 Core Drives reference:
{drives_block}

Lifecycle stages and goals:
{stages_block}

TASK: Using the Ethical Communication Guidelines in the KB above, generate the
allowed_tone_hook_matrix for each lifecycle stage. The allowed_tones and
disallowed_tones MUST be grounded in what the KB states.

For each lifecycle stage also choose:
  - primary_drives   : top 3 Octolysis drives most effective for users at this stage
  - secondary_drives : 2 supporting drives
  - hook_intensity   : "high" | "medium" | "low"
  - tone_rationale   : 1-2 sentences referencing both KB guidelines and behavioral data

Also generate a hook_taxonomy: one entry for EACH of the 8 Octolysis drives with:
  - core_drive     : exact drive name
  - application    : one short sentence explaining how this drive applies to SpeakX users
  - example_phrases: exactly 2 phrases — first in English, second in conversational Hindi

Return ONLY valid JSON:
{{
  "matrix": [
    {{
      "lifecycle_stage":  "<stage>",
      "allowed_tones":    ["<from KB guidelines>"],
      "disallowed_tones": ["<from KB guidelines>"],
      "primary_drives":   ["<drive_name>", "<drive_name>", "<drive_name>"],
      "secondary_drives": ["<drive_name>", "<drive_name>"],
      "hook_intensity":   "<high|medium|low>",
      "tone_rationale":   "<grounded in KB + behavioral stats>"
    }}
  ],
  "hook_taxonomy": [
    {{"core_drive": "Epic Meaning",     "application": "<one sentence>", "example_phrases": ["<English>", "<Hindi>"]}},
    {{"core_drive": "Accomplishment",   "application": "<one sentence>", "example_phrases": ["<English>", "<Hindi>"]}},
    {{"core_drive": "Empowerment",      "application": "<one sentence>", "example_phrases": ["<English>", "<Hindi>"]}},
    {{"core_drive": "Ownership",        "application": "<one sentence>", "example_phrases": ["<English>", "<Hindi>"]}},
    {{"core_drive": "Social Influence", "application": "<one sentence>", "example_phrases": ["<English>", "<Hindi>"]}},
    {{"core_drive": "Scarcity",         "application": "<one sentence>", "example_phrases": ["<English>", "<Hindi>"]}},
    {{"core_drive": "Unpredictability", "application": "<one sentence>", "example_phrases": ["<English>", "<Hindi>"]}},
    {{"core_drive": "Loss Avoidance",   "application": "<one sentence>", "example_phrases": ["<English>", "<Hindi>"]}}
  ],
  "global_disallowed": ["<tones the KB explicitly bans for all stages>"],
  "source": "KB Ethical Communication Guidelines",
  "bilingual_note": "All messages must be available in Hindi and English",
  "generated_at": "2026-03-07",
  "iteration": 0
}}""",
        temperature=0,
    )

    data = safe_parse_json(raw, fallback=_default_matrix())

    if isinstance(data, dict) and "matrix" in data:
        # Patch missing lifecycle stages
        existing_stages = {e.get("lifecycle_stage") for e in data["matrix"]}
        for stage in LIFECYCLE_STAGES:
            if stage not in existing_stages:
                data["matrix"].append(_default_stage_entry(stage))
        # Patch missing hook_taxonomy
        if "hook_taxonomy" not in data or len(data["hook_taxonomy"]) < 8:
            data["hook_taxonomy"] = _default_hook_taxonomy()
    else:
        data = _default_matrix()

    save_json(data, "allowed_tone_hook_matrix.json", output_dir)
    return data


# ── Fallback defaults ─────────────────────────────────────────

def _default_hook_taxonomy() -> list:
    return [
        {"core_drive": "Epic Meaning",     "application": "Connect English learning to career transformation and life goals.", "example_phrases": ["Join 1M+ learners changing their lives", "Apni zindagi badlo, aaj se shuru karo"]},
        {"core_drive": "Accomplishment",   "application": "Celebrate streaks, completed lessons, and progress milestones.", "example_phrases": ["You completed 5 lessons! Keep going!", "Aapne 5 lessons kiye — kya baat hai!"]},
        {"core_drive": "Empowerment",      "application": "Let users choose topics, pace, and practice scenarios freely.", "example_phrases": ["Choose your next speaking topic", "Aaj kya sikhna chahte ho? Aap choose karo"]},
        {"core_drive": "Ownership",        "application": "Make coins, streaks, and progress feel personally owned.", "example_phrases": ["Your 50 coins are waiting to be spent", "Tumhare 50 coins pade hain — use karo!"]},
        {"core_drive": "Social Influence", "application": "Show leaderboard rank and friend activity to trigger social proof.", "example_phrases": ["3 friends joined this week. Invite more!", "Tere 3 dost aa gaye — tu bhi aage badh!"]},
        {"core_drive": "Scarcity",         "application": "Highlight limited trial days to create urgency.", "example_phrases": ["Only 2 days left in your trial!", "Sirf 2 din bache hain — abhi complete karo!"]},
        {"core_drive": "Unpredictability", "application": "Surprise rewards and mystery challenges keep users curious.", "example_phrases": ["Surprise reward inside today's lesson!", "Aaj ke lesson mein ek surprise hai!"]},
        {"core_drive": "Loss Avoidance",   "application": "Protect streak anxiety to drive daily check-ins.", "example_phrases": ["Your 7-day streak is at risk!", "Tera 7-din ka streak toot sakta hai!"]},
    ]


def _default_stage_entry(stage: str) -> dict:
    defaults = {
        "trial":    {"allowed_tones": ["encouraging", "curious", "warm", "clear"],          "disallowed_tones": ["aggressive", "fear-based", "pressure-heavy"],  "primary_drives": ["Scarcity", "Empowerment", "Accomplishment"],          "secondary_drives": ["Epic Meaning", "Unpredictability"],    "hook_intensity": "high",   "tone_rationale": "Trial users need activation energy without feeling pressured."},
        "paid":     {"allowed_tones": ["motivating", "celebratory", "competitive", "personalized"], "disallowed_tones": ["aggressive", "guilt-tripping"],          "primary_drives": ["Accomplishment", "Loss Avoidance", "Social Influence"], "secondary_drives": ["Ownership", "Unpredictability"],       "hook_intensity": "medium", "tone_rationale": "Paid users respond to progress affirmation and streak protection."},
        "churned":  {"allowed_tones": ["empathetic", "value-reminder", "gentle", "nostalgic"],      "disallowed_tones": ["accusatory", "pressure-heavy", "boastful"],       "primary_drives": ["Epic Meaning", "Loss Avoidance", "Empowerment"],      "secondary_drives": ["Unpredictability", "Accomplishment"],  "hook_intensity": "low",    "tone_rationale": "Churned users need a soft re-entry narrative, not sales pressure."},
        "inactive": {"allowed_tones": ["warm", "concerned", "FOMO-light", "achievement-reminder"],  "disallowed_tones": ["aggressive", "shaming"],                  "primary_drives": ["Loss Avoidance", "Epic Meaning", "Unpredictability"],  "secondary_drives": ["Social Influence", "Scarcity"],        "hook_intensity": "medium", "tone_rationale": "Inactive users respond to streak-loss warnings and social proof."},
    }
    return {"lifecycle_stage": stage, **defaults.get(stage, {
        "allowed_tones": ["neutral", "informative"], "disallowed_tones": ["aggressive"],
        "primary_drives": ["Accomplishment"], "secondary_drives": ["Epic Meaning"],
        "hook_intensity": "medium", "tone_rationale": "Default moderate tone.",
    })}


def _default_matrix() -> dict:
    return {
        "matrix":           [_default_stage_entry(s) for s in LIFECYCLE_STAGES],
        "hook_taxonomy":    _default_hook_taxonomy(),
        "global_disallowed": ["shaming", "threatening", "deceptive", "guilt-tripping"],
        "source":           "fallback defaults",
        "bilingual_note":   "All messages must be available in Hindi and English",
        "generated_at":     "2026-03-07",
        "iteration":        0,
    }