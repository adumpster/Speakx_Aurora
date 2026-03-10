Project Aurora — Self-Learning Notification Orchestrator
SpeakX / KRITI 2026
================================================================================

ARCHITECTURE
────────────
Domain-agnostic orchestrator: swap user_behavioral_data.csv + knowledge context
and the same pipeline produces outputs for any B2C/B2B domain.

No RAG / No Vector DB — context injected directly from CSV statistics and a
knowledge bank (speakx_kb.txt / knowledge_bank.md) into LLM prompts.
Requires only Ollama running locally.

FILE STRUCTURE
────────────────
config.py                — All constants (model, paths, thresholds, drives)
llm.py                   — Ollama wrapper + JSON parsing + file save helpers
data_loader.py           — CSV loading, schema validation, derived signals, summary
kb_loader.py             — Loads and injects knowledge bank context into prompts
gen_north_star.py        — Generates company_north_star.json
gen_feature_goal_map.py  — Generates feature_goal_map.json
gen_tone_hook_matrix.py  — Generates allowed_tone_hook_matrix.json
segmentation_engine.py   — Generates user_segments.csv (MECE, 6-12 segments)
goal_builder.py          — Generates segment_goals.csv
comm_themes.py           — Generates communication_themes.csv
message_template_gen.py  — Generates message_templates.csv (5 per combination)
timing_optimizer.py      — Generates timing_recommendations.csv
notification_scheduler.py— Generates user_notification_schedule.csv
learning_engine.py       — Task 3: classifies results, learns, outputs Iteration 1
main.py                  — CLI orchestrator with per-step control

SETUP
──────
1. Install Ollama: https://ollama.com
2. Pull model:  ollama pull llama3.2:3b
3. pip install pandas requests

RUN INSTRUCTIONS
─────────────────
# Full pipeline (all tasks):
python main.py

# Task 1 only:
python main.py --steps task1

# Task 2 only (needs Task 1 outputs already in iteration_0_before_learning/):
python main.py --steps task2

# Single step:
python main.py --steps north_star
python main.py --steps segments goals

# Learning engine (Task 3 — needs experiment_results.csv from SpeakX):
python main.py --steps task3

# Custom data file:
python main.py --data /path/to/your_data.csv

# List all steps:
python main.py --list

OUTPUTS
────────
iteration_0_before_learning/
  company_north_star.json
  feature_goal_map.json
  allowed_tone_hook_matrix.json
  user_segments.csv
  segment_goals.csv
  communication_themes.csv
  message_templates.csv
  timing_recommendations.csv
  user_notification_schedule.csv

iteration_1_after_learning/
  message_templates.csv       (improved)
  timing_recommendations.csv  (learned)
  user_segments.csv(unchanged)
  user_notification_schedule.csv
  learning_delta_report.csv
  

MODELS
───────
Generation : llama3.2:3b (configurable in config.py → GEN_MODEL)

DOMAIN AGNOSTICITY
───────────────────
To use with a different domain:
  1. Replace user_behavioral_data.csv with new domain CSV
     (keep same column schema, or update REQUIRED_COLUMNS in data_loader.py)
  2. Replace speakx_kb.txt with domain-specific knowledge bank
  3. Update company-specific strings in config.py 
  4. Run python main.py — the system auto-discovers features, segments, goals
