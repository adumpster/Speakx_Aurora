# Project Overview — Project Aurora

> **Self-Learning Notification Orchestrator**
> SpeakX / KRITI 2026

---

## 1. What is Project Aurora?

Project Aurora is a **self-learning notification orchestrator**. It takes two inputs —
a company **Knowledge Bank** (a plain-text/markdown brief about the business) and a
**user behavioral CSV** (per-user activity data) — and produces a complete, personalized,
bilingual (English + Hindi) push-notification strategy. It then **learns from real-world
performance data** and autonomously rewrites its own outputs to improve the next campaign.

The system is built to be **domain-agnostic**: swap the Knowledge Bank and the CSV for a
different company (FinTech, SaaS, e-commerce, etc.) and the entire pipeline re-purposes
itself with no code changes — feature names, tones, goals, and metrics are all discovered
at runtime, never hardcoded.

All text generation runs on a **local LLM via Ollama** (`llama3.2:3b` by default), so the
system is fully offline and has no API/token cost.

---

## 2. The Two Phases

Aurora operates as a continuous loop of two phases.

### Phase 1 — Foundational Intelligence (Iteration 0)

Builds the initial messaging strategy from scratch. Produces nine artifacts written to
`iteration_0_before_learning/`:

| # | Artifact | What it answers |
|---|----------|-----------------|
| 1 | `company_north_star.json` | *What single metric defines success?* |
| 2 | `feature_goal_map.json` | *Which product feature drives which goal?* |
| 3 | `allowed_tone_hook_matrix.json` | *What tones are allowed, and how do Octalysis drives apply?* |
| 4 | `user_segments.csv` | *Who are the users? (MECE behavioral cohorts)* |
| 5 | `segment_goals.csv` | *What is the goal for each segment at each lifecycle phase?* |
| 6 | `communication_themes.csv` | *What psychological theme + tone fits each segment × phase?* |
| 7 | `message_templates.csv` | *The actual bilingual copy — 5 templates per combination.* |
| 8 | `timing_recommendations.csv` | *When should each segment be messaged?* |
| 9 | `user_notification_schedule.csv` | *The final "what to send, to whom, when" plan.* |

### Phase 2 — Self-Learning Feedback Loop (Iteration 1)

Consumes real-world performance feedback (`experiment_results.csv`, provided during the
demo) and autonomously adapts. Produces updated artifacts in `iteration_1_after_learning/`
plus an auditable `learning_delta_report.csv` explaining every change:

- **GOOD** templates → kept as-is and used as style references.
- **NEUTRAL** templates → same theme, sharper/punchier hook (A/B candidates).
- **BAD** templates → suppressed, theme swapped, fully rewritten by the LLM.
- **Timing** → shifted to each segment's historically best-performing window.
- **Frequency** → reduced (−2 notifications) for any segment breaching the uninstall guardrail.

---

## 3. Core Design Principles

1. **Domain agnosticism.** No product name, feature name, or tone is hardcoded in the
   pipeline logic. Features are auto-discovered from `feature_*` CSV columns; tones are
   extracted from the KB; propensities adapt to whatever features exist.

2. **Deterministic where it counts, LLM where it adds value.** Segmentation, scoring,
   timing, scheduling, and guardrail enforcement are **pure Python** (reproducible, no
   randomness). The LLM is used only for creative/strategic text generation (north star
   justification, goals, themes, copy).

3. **Full KB injection, no RAG.** The KB is small (~2–4k chars), so it is injected whole
   into every prompt. This is strictly better than retrieval for a document this size —
   nothing is missed and there is no vector-DB infrastructure to maintain. See
   [ARCHITECTURE.md](ARCHITECTURE.md).

4. **Graceful degradation.** Every LLM call has a hand-written fallback. If Ollama is down,
   the JSON is malformed, or a file is missing, the pipeline still produces valid output.

5. **Auditability.** The learning phase writes a causal delta report — every promotion,
   suppression, timing shift, and frequency cut is logged with its trigger and explanation.

---

## 4. Frameworks & Concepts Used

- **Octalysis (8 Core Drives)** — the gamification framework used to classify psychological
  hooks: Epic Meaning, Accomplishment, Empowerment, Ownership, Social Influence, Scarcity,
  Unpredictability, Loss Avoidance. (Referenced in code as `OCTOLYSIS_DRIVES` / "Octolysis".)
- **RFM-style activeness scoring** — Recency (notif open rate), Frequency (sessions),
  Magnitude (exercises + streak) composited into a 0–1 `activeness_score`.
- **MECE segmentation** — 13 mutually-exclusive, collectively-exhaustive behavioral
  segments plus 1 catch-all.
- **11-phase lifecycle model** — granular day-by-day phases across trial, paid, churned,
  and inactive stages.

---

## 5. Where to Go Next

| I want to… | Read |
|------------|------|
| Install and run it | [INSTALLATION.md](INSTALLATION.md), [QUICK_START.md](QUICK_START.md) |
| Understand the design | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Know what each file/module does | [APP_STRUCTURE.md](APP_STRUCTURE.md) |
| Call the functions programmatically | [API_REFERENCE.md](API_REFERENCE.md) |
| Understand every input/output schema | [DATA_FORMATS.md](DATA_FORMATS.md) |
| Learn about the LLM / model config | [MODELS_DOCUMENTATION.md](MODELS_DOCUMENTATION.md) |
| See the full build summary | [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) |
