# config.py
# ─────────────────────────────────────────────────────────────────────────────
# All project-wide constants. Change here → reflects everywhere automatically.
# ─────────────────────────────────────────────────────────────────────────────

# ── Ollama settings ───────────────────────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434"
GEN_MODEL  = "llama3.2:3b"              # text generation model

# ── File / folder paths ───────────────────────────────────────────────────────
from pathlib import Path

# Project root: .../aurora_codebase
BASE_DIR = Path(__file__).resolve().parent.parent

KB_PATH        = str(BASE_DIR / "knowledge_bank.md")                 # company knowledge base (plain text / markdown)
USER_DATA_PATH = str(BASE_DIR / "user_behavioral_data.csv")      # input behavioural CSV
OUTPUT_DIR     = str(BASE_DIR / "iteration_0_before_learning")   # primary output dir (Task 1 & 2)
OUTPUT_DIR_0   = OUTPUT_DIR                                     # alias (before learning)
OUTPUT_DIR_1   = str(BASE_DIR / "iteration_1_after_learning")    # after learning (Task 3)
EXPERIMENT_RESULTS_PATH = str(BASE_DIR / "experiment_results.csv")

# ── KB injection settings (no RAG — plain text injection) ────────────────────
# Increase KB_MAX_CHARS if your model supports a larger context window.
KB_MAX_CHARS = 4000   # max characters of KB text sent per LLM call

# ── Octolysis 8 Core Drives (domain-agnostic reference) ──────────────────────
OCTOLYSIS_DRIVES = [
    {"id": 1, "name": "Epic Meaning",     "example": "Join 1M+ learners transforming their careers",
     "hook": "Join 1M+ learners transforming their careers"},
    {"id": 2, "name": "Accomplishment",   "example": "You completed 5 lessons! Keep the momentum",
     "hook": "You completed 5 lessons! Keep the momentum"},
    {"id": 3, "name": "Empowerment",      "example": "Choose your learning path today",
     "hook": "Choose your learning path today"},
    {"id": 4, "name": "Ownership",        "example": "Your 50 coins are waiting to be spent",
     "hook": "Your 50 coins are waiting to be spent"},
    {"id": 5, "name": "Social Influence", "example": "3 friends joined this week. Invite more!",
     "hook": "3 friends joined this week. Invite more!"},
    {"id": 6, "name": "Scarcity",         "example": "Only 2 days left in your trial!",
     "hook": "Only 2 days left in your trial!"},
    {"id": 7, "name": "Unpredictability", "example": "Surprise reward inside today's lesson!",
     "hook": "Surprise reward inside today's lesson!"},
    {"id": 8, "name": "Loss Avoidance",   "example": "Your 7-day streak is at risk!",
     "hook": "Your 7-day streak is at risk!"},
]

# ── Standard notification time windows ───────────────────────────────────────
TIME_WINDOWS = [
    {"name": "early_morning",  "range": "06:00-08:59", "start": 6,  "end": 9,
     "use": "Morning motivation, habit trigger"},
    {"name": "mid_morning",    "range": "09:00-11:59", "start": 9,  "end": 12,
     "use": "Work break reminder"},
    {"name": "afternoon",      "range": "12:00-14:59", "start": 12, "end": 15,
     "use": "Lunch break engagement"},
    {"name": "late_afternoon", "range": "15:00-17:59", "start": 15, "end": 18,
     "use": "Productivity boost"},
    {"name": "evening",        "range": "18:00-20:59", "start": 18, "end": 21,
     "use": "Post-work learning"},
    {"name": "night",          "range": "21:00-23:59", "start": 21, "end": 24,
     "use": "End-of-day recap, streak save"},
]

# ── Notification frequency bands ─────────────────────────────────────────────
FREQ_BANDS = [
    {"min": 0.7, "max": 1.0, "notifs_per_day_range": (7, 9), "label": "high_active"},
    {"min": 0.4, "max": 0.7, "notifs_per_day_range": (5, 6), "label": "moderate"},
    {"min": 0.0, "max": 0.4, "notifs_per_day_range": (3, 4), "label": "low_active"},
]
GUARDRAIL_UNINSTALL_RATE = 0.02  # reduce freq by 2 if uninstall_rate > this

# ── Template classification thresholds ───────────────────────────────────────
TEMPLATE_THRESHOLDS = {
    "GOOD":    {"ctr_min": 0.15, "engagement_min": 0.40},
    "NEUTRAL": {"ctr_min": 0.05, "engagement_min": 0.20},
    "BAD":     {"ctr_min": 0.00, "engagement_min": 0.00},
}

# ── Lifecycle stage definitions ───────────────────────────────────────────────
LIFECYCLE_STAGES = {
    "trial":    {"day_range": "D0-D7",  "primary_goal": "Activate user, trigger first habit"},
    "paid":     {"day_range": "D8-D30", "primary_goal": "Drive retention and feature depth"},
    "churned":  {"day_range": "D31+",   "primary_goal": "Re-engage and win back"},
    "inactive": {"day_range": "D31+",   "primary_goal": "Reactivate before permanent churn"},
}
