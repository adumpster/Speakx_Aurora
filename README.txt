Project Aurora — Self-Learning Notification Orchestrator
SpeakX / KRITI 2026
================================================================================

Project Aurora is a smart, self-learning notification orchestrator designed to deliver highly personalized user communication. It operates in two continuous phases: Phase 1 creates an initial messaging strategy based on company goals and user behavior, while Phase 2 learns from real-world performance data to autonomously adapt and improve future campaigns.

Phase 1: Foundational Intelligence (Iteration 0)

company_north_star.json
Extracts the primary guiding metric from the Knowledge Bank. Defines exactly how to measure overall success and justifies its selection.

feature_goal_map.json
Maps each product feature to specific user goals and lifecycle stages. Determines which features to push based on empirical usage rates.

allowed_tone_hook_matrix.json
Extracts permitted communication tones and builds an Octolysis-based hook taxonomy. Ensures all generated messaging strictly adheres to brand safety guidelines.

user_segments.csv
Groups users into MECE (mutually exclusive, collectively exhaustive) behavioral cohorts. Computes activeness, churn risk, and dynamic feature propensity scores.

segment_goals.csv
Establishes primary goals and day-by-day engagement plans. Tailors the strategy dynamically for each segment across all state-bound and time-bound lifecycle phases.

communication_themes.csv
Matches the best Octolysis core drives and tones to specific segments and phases. Generates foundational English and Hindi hook concepts to drive the templates.

message_templates.csv
Contains the fully fleshed-out, bilingual notification copy. Generates exactly 5 distinct templates per segment/goal/theme combination.

timing_recommendations.csv
Proposes the best standard time windows for message delivery based on segment behaviors. Balances engagement likelihood with user fatigue.

user_notification_schedule.csv
The final output of Phase 1 detailing exactly what to send, to whom, and when. Assigns daily templates and frequencies (3-9 per day) while respecting uninstall guardrails.

Phase 2: Self-Learning Feedback Loop (Iteration 1)

experiment_results.csv
The real-world performance feedback injected into the system (provided during the demo). Contains exact CTR, engagement, and uninstall rates for Phase 1's outputs.

learning_delta_report.csv
A comprehensive, auditable trail of what the system learned and changed. Documents causal explanations for promoting good templates or suppressing bad ones.




FILE STRUCTURE
────────────────
(we have uploaded our the outpusts based on our dummy and sample data)
|---iteration_0_before_learning/   — Directory containing baseline strategies before experiments
|---iteration_1_after_learning/    — Directory containing updated strategies post-experiment
|---codebase/
|   |---data_loader.py           — CSV loading, schema validation, derived signals, summary
|   |---kb_loader.py             — Loads and injects knowledge bank context into prompts
|   |---gen_north_star.py        — Generates company_north_star.json
|   |---gen_feature_goal_map.py  — Generates feature_goal_map.json
|   |---gen_tone_hook_matrix.py  — Generates allowed_tone_hook_matrix.json
|   |---segmentation_engine.py   — Generates user_segments.csv (MECE, 14 segments)
|   |---goal_builder.py          — Generates segment_goals.csv
|   |---comm_themes.py           — Generates communication_themes.csv
|   |---message_template_gen.py  — Generates message_templates.csv (5 per combination)
|   |---timing_optimizer.py      — Generates timing_recommendations.csv
|   |---notification_scheduler.py— Generates user_notification_schedule.csv
|   |---learning_engine.py       — Task 3: classifies results, learns, outputs Iteration 1
|   |---main.py                  — CLI orchestrator with per-step control
|---experimen_results.csv
|---learning_delta_report.csv
|---user_behavioral_data.csv(dummy data to be replaced in demo)
|---knowledge_bank.md(dummy data to be replaced in demo)
|---README.txt


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

# if any terminal timeout errors occur rerun the step

MODELS
───────
Generation : llama3.2:3b (configurable in config.py → GEN_MODEL)


