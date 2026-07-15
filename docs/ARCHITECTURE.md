# Architecture — Project Aurora

This document describes how the system is designed: the pipeline stages, the flow of data
between them, the split between deterministic and LLM-driven logic, and the key design
decisions.

---

## 1. High-Level Data Flow

```
                    ┌──────────────────────────┐
  knowledge_bank.md │  INPUTS                  │  user_behavioral_data.csv
        (KB text) ─►│                          │◄─ (per-user activity)
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  data_loader.py          │  load → clean → derive signals →
                    │  → DataProfile           │  build summary
                    └────────────┬─────────────┘
                                 │  (profile.df, profile.summary, profile.feature_cols)
        ┌────────────────────────┼───────────────────────────────┐
        │        TASK 1 — Foundational Intelligence                │
        │                                                          │
        │  north_star ─► features ─► tone_matrix                   │
        │       │            │            │                        │
        │       └──────► segments ─► goals ◄──────────────────────┤
        └────────────────────────┬───────────────────────────────┘
                                 │
        ┌────────────────────────┼───────────────────────────────┐
        │        TASK 2 — Communication Generation                 │
        │                                                          │
        │  themes ─► templates ─► timing ─► schedule               │
        └────────────────────────┬───────────────────────────────┘
                                 │        writes → iteration_0_before_learning/
                                 │
                    ┌────────────▼─────────────┐
                    │  experiment_results.csv  │  (real-world CTR / engagement / uninstall)
                    └────────────┬─────────────┘
                                 │
        ┌────────────────────────┼───────────────────────────────┐
        │        TASK 3 — Self-Learning Engine (5 phases)          │
        │                                                          │
        │  ingest+classify ─► timing ─► template evolution ─►      │
        │  schedule regen + guardrails ─► delta report             │
        └────────────────────────┬───────────────────────────────┘
                                 │        writes → iteration_1_after_learning/
                                 ▼                 + learning_delta_report.csv
```

The orchestrator (`main.py`) invokes each stage in dependency order and passes results
in-memory via a `state` dict, falling back to reading from disk when a step is run in
isolation.

---

## 2. The Three Tasks

### Task 1 — Foundational Intelligence
Establishes *strategy*: the north star metric, the feature→goal map, the tone/hook policy,
the user segments, and per-segment/per-phase goals.

**Steps:** `north_star` → `features` → `tone_matrix` → `segments` → `goals`

### Task 2 — Communication Generation
Turns strategy into *deliverables*: themes, actual bilingual copy, timing windows, and the
final schedule.

**Steps:** `themes` → `templates` → `timing` → `schedule`

### Task 3 — Self-Learning
Reads performance feedback and *evolves* the outputs.

**Steps:** `learning` (a single step that runs a 5-phase internal pipeline)

> `main.py`'s `all` alias runs Task 1 + Task 2 only. `learning` (Task 3) is deliberately
> excluded from `all` because it requires `experiment_results.csv`, which only exists after
> a real campaign has run.

---

## 3. Deterministic vs. LLM Split

A deliberate architectural boundary separates *reproducible computation* from *creative
generation*.

| Stage | Engine | Why |
|-------|--------|-----|
| Data loading, signal derivation | **Deterministic** | Scores must be reproducible |
| `user_segments.csv` (segmentation) | **Deterministic** | MECE rules, percentile bands — no randomness |
| `timing_recommendations.csv` | **Deterministic** | Pure statistics over preferred hours |
| `user_notification_schedule.csv` | **Deterministic** | Grid expansion + assignment logic |
| Learning: classify / guardrails / timing / schedule | **Deterministic** | Auditable, threshold-based |
| `company_north_star.json` | **LLM** | Extraction + justification |
| `feature_goal_map.json` | **LLM** | Strategic mapping |
| `allowed_tone_hook_matrix.json` | **LLM** | Tone extraction + hook taxonomy |
| `segment_goals.csv` | **LLM** | Per-phase goal design |
| `communication_themes.csv` | **LLM** | Theme + tone + hook selection |
| `message_templates.csv` | **LLM** | Bilingual copywriting |
| Learning: template rewrite/iterate | **LLM** | Creative copy improvement |

Every LLM stage has a **hand-written deterministic fallback**, so the pipeline never hard-fails
on a bad model response.

---

## 4. Knowledge Injection Strategy — "No RAG"

The KB is intentionally small (~2,000–4,000 characters). For a document this size, **full
injection beats retrieval**:

- Nothing is dropped by a retrieval step — the model sees the whole business context.
- No ChromaDB, embeddings, or vector infrastructure to run or maintain.
- `kb_loader.build_context()` concatenates **[full KB text] + [behavioral data summary]**
  and hands that to every generator, so the LLM always reasons from *both* company
  knowledge and real user numbers simultaneously.

`KB_MAX_CHARS` in `config.py` bounds how much KB text is sent per call; raise it if your
model supports a larger context window. The KB file is cached in-module after first read.

---

## 5. Domain Agnosticism

The pipeline never hardcodes product specifics. The mechanisms:

- **Feature discovery.** Any CSV column named `feature_<name>` is auto-detected. For each,
  a `propensity_<name>` signal is computed (`0.6 × usage_flag + 0.4 × motivation_score`).
  Swap the CSV → all propensity columns adapt.
- **Dominant propensity.** Each user's highest `propensity_*` column becomes their
  `dominant_propensity`, used to sub-split segments — with no knowledge of what the feature is.
- **Tone extraction.** Allowed/disallowed tones are pulled from the KB's *Ethical
  Communication Guidelines* section, not invented.
- **North star extraction.** Read directly from the KB if stated; otherwise inferred via a
  structured scoring prompt.

The Octalysis 8 Core Drives (`OCTOLYSIS_DRIVES`) and the standard time windows
(`TIME_WINDOWS`) are the only fixed reference taxonomies — and both are domain-neutral.

---

## 6. Concurrency & Reliability

- **Concurrency.** The two heaviest LLM stages (`comm_themes.py`,
  `message_template_gen.py`) parallelize Ollama calls with a
  `ThreadPoolExecutor` (default `max_workers=2`) to cut wall-clock time while keeping the
  local model from being overwhelmed.
- **Retries.** `message_template_gen.py` retries up to `MAX_RETRIES = 3` times if the LLM
  returns fewer than the required 5 templates, then pads with fallback rows.
- **Robust JSON parsing.** `llm.parse_json()` strips markdown fences and falls through three
  sanitization tiers (standard parse → escape/control-char fixing → regex field extraction)
  before giving up. `safe_parse_json()` wraps this with a caller-supplied fallback.
- **Fault isolation in the orchestrator.** `main.py` wraps every step in try/except; a
  failed step is logged and the pipeline continues, reporting failed steps at the end.

---

## 7. The Learning Engine (5-Phase) Internals

`learning_engine.run_learning_engine()` runs five internal phases:

1. **Data Ingestion & State Evaluation** *(deterministic)* — load `experiment_results.csv`,
   normalize its schema (supports legacy + new column names, backfills rates from totals),
   classify each row GOOD/NEUTRAL/BAD against `TEMPLATE_THRESHOLDS`, compute
   send-weighted uninstall guardrails per segment, and score timing performance per
   segment × window.
2. **Timing & Frequency Resolution** *(deterministic)* — shift each segment to its
   highest `combined_score` window; update expected metrics to observed actuals.
3. **Template Evolution** *(hybrid)* — merge performance back onto Iteration 0 templates
   (direct `template_id` merge, with a fallback to normalized `segment_id + theme`, then a
   segment-level backfill). GOOD kept, NEUTRAL LLM-iterated (same theme, punchier),
   BAD LLM-rewritten with a forced new theme + rotating creative angle; rewritten IDs get a
   `_v2` suffix and retain a `source_template_id` for A/B lineage.
4. **Schedule Regeneration** *(deterministic)* — re-map new template IDs and windows into
   the wide-format schedule; apply the guardrail penalty (clear the last 2 populated
   notification cells) for breached segments.
5. **Delta Report Compilation** — write `learning_delta_report.csv` with a causal row for
   every change, plus a printed summary.

See [API_REFERENCE.md](API_REFERENCE.md) for the exact function signatures.

---

## 8. Key Configuration Knobs (`config.py`)

| Constant | Purpose |
|----------|---------|
| `GEN_MODEL`, `OLLAMA_URL` | Which local model and endpoint to use |
| `KB_MAX_CHARS` | KB text budget per prompt |
| `OCTOLYSIS_DRIVES` | The 8 gamification drives (id, name, example hook) |
| `TIME_WINDOWS` | 6 standard delivery windows (06:00–24:00) |
| `FREQ_BANDS` | Activeness → notifications-per-day mapping |
| `GUARDRAIL_UNINSTALL_RATE` | Uninstall threshold (0.02) triggering frequency cuts |
| `TEMPLATE_THRESHOLDS` | CTR/engagement cutoffs for GOOD/NEUTRAL/BAD |
| `LIFECYCLE_STAGES` | trial / paid / churned / inactive definitions |
| `OUTPUT_DIR_0`, `OUTPUT_DIR_1` | Iteration output directories |
