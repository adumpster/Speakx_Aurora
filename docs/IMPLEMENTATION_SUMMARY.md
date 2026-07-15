# Implementation Summary — Project Aurora

A condensed, end-to-end account of what was built, how the pieces fit, and the notable
engineering decisions. Use this as the "single-sitting" read that ties every other doc
together.

---

## 1. What Was Built

A three-task, two-iteration notification orchestrator:

- **Task 1 — Foundational Intelligence** (5 steps): north star, feature→goal map, tone/hook
  matrix, MECE user segments, per-segment/per-phase goals.
- **Task 2 — Communication Generation** (4 steps): themes, 5-per-combo bilingual message
  templates, timing recommendations, final wide-format schedule.
- **Task 3 — Self-Learning Engine** (1 step, 5 internal phases): ingest performance,
  classify, resolve timing, evolve templates (hybrid rules + LLM), regenerate schedule with
  guardrails, and emit an auditable delta report.

All orchestrated by `main.py` with granular step/alias control, running on a local Ollama
model with full-KB prompt injection and no external services.

---

## 2. Pipeline at a Glance

| Step | Module | Output | Engine |
|------|--------|--------|--------|
| `north_star` | `gen_north_star.py` | `company_north_star.json` | LLM (3-layer) |
| `features` | `gen_feature_goal_map.py` | `feature_goal_map.json` | LLM (per feature) |
| `tone_matrix` | `gen_tone_hook_matrix.py` | `allowed_tone_hook_matrix.json` | LLM (2-pass) |
| `segments` | `segmentation_engine.py` | `user_segments.csv` | Deterministic |
| `goals` | `goal_builder.py` | `segment_goals.csv` | LLM (per segment×phase) |
| `themes` | `comm_themes.py` | `communication_themes.csv` | LLM (concurrent) |
| `templates` | `message_template_gen.py` | `message_templates.csv` | LLM (concurrent, retries) |
| `timing` | `timing_optimizer.py` | `timing_recommendations.csv` | Deterministic |
| `schedule` | `notification_scheduler.py` | `user_notification_schedule.csv` | Deterministic |
| `learning` | `learning_engine.py` | iteration_1 + delta report | Hybrid |

---

## 3. Data & Scoring Model

From the behavioral CSV, `data_loader.add_derived_signals` computes:

- **`activeness_score`** = `0.30·Recency + 0.40·Frequency + 0.30·Magnitude`
  - Recency = 30-day notif open rate; Frequency = sessions/7d (capped at 14); Magnitude =
    ½·exercises/21 + ½·streak/30. Frequency is weighted highest as the strongest short-term
    retention predictor.
- **`churn_risk_score`** = `0.35·inactive + 0.25·zero_sessions + 0.20·zero_streak + 0.20·(1−open_rate)`.
- **`propensity_<feature>`** = `0.6·usage_flag + 0.4·motivation` for every `feature_*` column
  (domain-agnostic; auto-discovered).

Segmentation (`segmentation_engine`) is pure Python: dominant propensity per user → percentile
activeness bands (33/67) → 13 MECE segments + 1 catch-all, split by lifecycle stage and
propensity/motivation thresholds.

---

## 4. Notable Engineering Decisions

1. **Deterministic/LLM boundary.** Anything that must be reproducible or auditable
   (segmentation, timing, scheduling, classification, guardrails) is pure Python; the LLM is
   confined to creative/strategic text. Every LLM stage has a coded fallback.

2. **Full-KB injection over RAG.** The KB is small enough that whole-document injection is
   strictly better than retrieval — simpler, lossless, zero infra. (`kb_loader.build_context`.)

3. **Domain agnosticism by construction.** No product/feature/tone strings are hardcoded in
   pipeline logic; features are discovered from `feature_*` columns, tones extracted from the
   KB, propensities computed generically. Swap KB + CSV → the pipeline re-purposes itself.

4. **Small, focused prompts.** Multi-layer (north star) and multi-pass (tone matrix) prompting
   and per-item calls (features, goals, themes, templates) beat monolithic prompts on a 3B
   model and fail independently.

5. **Robust parsing.** `parse_json` degrades through standard → sanitized → regex extraction;
   `safe_parse_json` guarantees a usable value.

6. **Concurrency with backpressure.** The two heavy LLM stages use a `ThreadPoolExecutor`
   (`max_workers=2`) — faster wall-clock without overwhelming the local model.

7. **Fault isolation.** `main.py` wraps each step in try/except and continues; state is passed
   in-memory but every step can reload upstream artifacts from disk, so single-step reruns work.

8. **Auditable learning.** Every learning change writes a causal row to
   `learning_delta_report.csv`; rewritten templates keep `source_template_id` and a `_v2` id for
   A/B lineage; uninstall guardrails use **send-weighted** rates to avoid Simpson's paradox.

---

## 5. The 5-Phase Learning Engine

1. **Ingest & Evaluate** — load `experiment_results.csv`, normalize schema (legacy/new,
   backfill rates from totals), classify GOOD/NEUTRAL/BAD, compute send-weighted uninstall
   guardrails, score segment×window timing.
2. **Timing Resolution** — shift each segment to its best `combined_score` window; set expected
   metrics to observed actuals.
3. **Template Evolution (hybrid)** — merge performance onto Iteration 0 (direct `template_id`,
   then normalized `segment_id+theme`, then segment-level backfill). GOOD kept as references;
   NEUTRAL LLM-iterated (same theme, punchier); BAD LLM-rewritten with forced new theme +
   rotating creative angle, id → `_v2`.
4. **Schedule Regeneration** — re-map new ids/windows into the wide schedule; clear the last 2
   populated notif cells for guardrail-breached segments.
5. **Delta Report** — write the causal change log + a printed summary.

---

## 6. Configuration Surface

Everything tunable lives in `config.py`: model/endpoint, paths, KB budget, the 8 Octalysis
drives, the 6 time windows, frequency bands, the uninstall guardrail (0.02), the
GOOD/NEUTRAL/BAD thresholds, and the lifecycle-stage definitions. See
[ARCHITECTURE.md §8](ARCHITECTURE.md) and [API_REFERENCE.md](API_REFERENCE.md).

---

## 7. Known Constraints & Notes

- **Two KB files** exist (`knowledge_bank.md`, `speakx_kb.txt`); `config.KB_PATH` points at the
  `.md`. Both are placeholder/demo content meant to be replaced.
- **LLM outputs are non-deterministic**; re-running a generator can change copy. Deterministic
  stages are fully reproducible.
- **`learning` is excluded from the `all` alias** because it needs `experiment_results.csv`,
  which exists only after a real campaign.
- **Timeouts** on slow machines are expected on the heaviest prompts — the intended remedy is
  to re-run the affected step (completed steps are cached to disk).
- **No `requirements.txt`**; dependencies are `pandas`, `numpy`, `requests` + stdlib.
- `timing_optimizer.gen_user_notification_schedule` is a long-format alternative; the wired
  `schedule` step uses `notification_scheduler.run_pipeline` (wide format).

---

## 8. Doc Map

- Big picture → [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)
- Design & flow → [ARCHITECTURE.md](ARCHITECTURE.md)
- Files & modules → [APP_STRUCTURE.md](APP_STRUCTURE.md)
- Setup → [INSTALLATION.md](INSTALLATION.md)
- Commands → [QUICK_START.md](QUICK_START.md)
- Functions → [API_REFERENCE.md](API_REFERENCE.md)
- Schemas → [DATA_FORMATS.md](DATA_FORMATS.md)
- LLM details → [MODELS_DOCUMENTATION.md](MODELS_DOCUMENTATION.md)
