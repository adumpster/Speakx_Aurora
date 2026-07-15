# Application Structure — Project Aurora

A map of the repository: every directory, every module, and the responsibilities of each.

---

## 1. Repository Layout

```
Speakx_Aurora/
├── codebase/                          # All Python source
│   ├── config.py                      # Project-wide constants & taxonomies
│   ├── llm.py                         # Ollama wrapper + robust JSON parsing + save helpers
│   ├── kb_loader.py                   # Knowledge Bank loading & prompt-context builder
│   ├── data_loader.py                 # CSV load, clean, derive signals, summarize
│   ├── gen_north_star.py              # Task 1 → company_north_star.json
│   ├── gen_feature_goal_map.py        # Task 1 → feature_goal_map.json
│   ├── gen_tone_hook_matrix.py        # Task 1 → allowed_tone_hook_matrix.json
│   ├── segmentation_engine.py         # Task 1 → user_segments.csv (deterministic)
│   ├── goal_builder.py                # Task 1 → segment_goals.csv (11-phase model)
│   ├── comm_themes.py                 # Task 2 → communication_themes.csv
│   ├── message_template_gen.py        # Task 2 → message_templates.csv (5 per combo)
│   ├── timing_optimizer.py            # Task 2 → timing_recommendations.csv (+schedule helper)
│   ├── notification_scheduler.py      # Task 2 → user_notification_schedule.csv (wide format)
│   ├── learning_engine.py             # Task 3 → iteration_1 outputs + delta report
│   └── main.py                        # CLI orchestrator (step control, aliases)
│
├── iteration_0_before_learning/       # Phase 1 outputs (baseline strategy)
│   ├── company_north_star.json
│   ├── feature_goal_map.json
│   ├── allowed_tone_hook_matrix.json
│   ├── user_segments.csv
│   ├── segment_goals.csv
│   ├── communication_themes.csv
│   ├── message_templates.csv
│   ├── timing_recommendations.csv
│   └── user_notification_schedule.csv
│
├── iteration_1_after_learning/        # Phase 2 outputs (post-learning strategy)
│   ├── message_templates.csv
│   ├── segment_goals.csv
│   ├── timing_recommendations.csv
│   └── user_notification_schedule.csv
│
├── user_behavioral_data.csv           # INPUT: per-user activity (demo/dummy data)
├── experiment_results.csv             # INPUT (Task 3): real-world performance feedback
├── knowledge_bank.md                  # INPUT: company KB (markdown, richer version)
├── speakx_kb.txt                      # INPUT: company KB (plain text, referenced by config)
├── README.txt                         # Original project readme
└── docs/                              # ← This documentation set
```

> **Note on the two KB files.** `config.py` sets `KB_PATH = BASE_DIR / "knowledge_bank.md"`.
> `speakx_kb.txt` is an alternate/plain-text version of the same content. To use it, point
> `KB_PATH` at it. Both are treated as "dummy data to be replaced in the demo".

---

## 2. Layered View of the Codebase

The modules fall into four layers.

### Layer A — Infrastructure (shared utilities)
| Module | Responsibility |
|--------|----------------|
| `config.py` | Single source of truth for constants: model IDs, paths, Octalysis drives, time windows, frequency bands, thresholds, lifecycle stages. Change here → reflected everywhere. |
| `llm.py` | `llm()` posts to Ollama's `/api/generate`. `parse_json()` / `safe_parse_json()` robustly extract JSON from model text. `save_json()` / `save_csv()` persist outputs. |
| `kb_loader.py` | `load_kb()` (cached), `get_kb_section()`, and `build_context()` which fuses full KB text with the behavioral data summary for prompt injection. |
| `data_loader.py` | `load_data()` (clean/coerce), `add_derived_signals()` (activeness, churn risk, propensities), `build_data_summary()`, `extract_features()`, and `load_and_profile()` → `DataProfile`. |

### Layer B — Task 1 generators (strategy)
| Module | Output | LLM? |
|--------|--------|------|
| `gen_north_star.py` | `company_north_star.json` | Yes (3-layer: extract → score → build) |
| `gen_feature_goal_map.py` | `feature_goal_map.json` | Yes (one call per discovered feature) |
| `gen_tone_hook_matrix.py` | `allowed_tone_hook_matrix.json` | Yes (2-pass: tones → taxonomy+matrix) |
| `segmentation_engine.py` | `user_segments.csv` | **No** — fully deterministic |
| `goal_builder.py` | `segment_goals.csv` | Yes (one call per segment × phase) |

### Layer C — Task 2 generators (communication)
| Module | Output | LLM? |
|--------|--------|------|
| `comm_themes.py` | `communication_themes.csv` | Yes (concurrent, per segment × phase) |
| `message_template_gen.py` | `message_templates.csv` | Yes (concurrent, 5 templates/combo, retries) |
| `timing_optimizer.py` | `timing_recommendations.csv` | **No** — statistics over preferred hours |
| `notification_scheduler.py` | `user_notification_schedule.csv` | **No** — grid expansion + assignment |

### Layer D — Task 3 (learning) & orchestration
| Module | Responsibility |
|--------|----------------|
| `learning_engine.py` | 5-phase self-learning: classify → resolve timing → evolve templates (hybrid) → regenerate schedule + guardrails → delta report. |
| `main.py` | CLI: parses `--steps`, resolves aliases, loads the `DataProfile` once, runs steps in order with fault isolation, prints a summary. |

---

## 3. Module Dependency Graph

```
config.py  ◄──────────────── (imported by nearly everything)
   ▲
   │
llm.py  ◄── kb_loader.py     data_loader.py
   ▲            ▲                  ▲
   │            │                  │
   ├── gen_north_star.py ──────────┤
   ├── gen_feature_goal_map.py ────┤
   ├── gen_tone_hook_matrix.py ────┤
   ├── segmentation_engine.py ─────┤
   ├── goal_builder.py ────────────┤
   ├── comm_themes.py ─────────────┤
   ├── message_template_gen.py ────┤
   ├── timing_optimizer.py ────────┤
   ├── notification_scheduler.py   │
   └── learning_engine.py ─────────┘
            ▲
            │
         main.py  (imports each generator lazily inside run_step)
```

`main.py` uses **lazy imports** — each generator is imported only when its step runs, so a
single-step run never pays the import cost of unrelated modules.

---

## 4. The Orchestrator: Steps & Aliases (`main.py`)

**Steps** (canonical names):
`north_star`, `features`, `tone_matrix`, `segments`, `goals`, `themes`, `templates`,
`timing`, `schedule`, `learning`.

**Aliases:**
| Alias | Expands to |
|-------|-----------|
| `task1` | north_star, features, tone_matrix, segments, goals |
| `task2` | themes, templates, timing, schedule |
| `task3` | learning |
| `all` | task1 + task2 (learning **excluded** by design) |

**State passing.** `run_step()` stores each result in a module-level `state` dict. Downstream
steps read from `state` first and fall back to loading the artifact from disk
(`_df_or_load`, `_load_json`, `_load_csv`) — this is what makes single-step reruns work.

CLI flags: `--steps`, `--data <csv>`, `--out0 <dir>`, `--list`. See
[QUICK_START.md](QUICK_START.md).

---

## 5. Standalone Runners

Several generators expose a `if __name__ == "__main__":` block with their own `argparse`,
so they can be run directly for debugging without the orchestrator:

- `goal_builder.py` — `--segments --behavioral --north-star --feature-map --tone-matrix --output-dir`
- `comm_themes.py` — `--segments --goals --matrix --behavioral --output-dir --workers`
- `message_template_gen.py` — `--themes --goals --segments --feature-map --behavioral --output-dir --workers`
- `notification_scheduler.py` — no args; runs `run_pipeline()` reading from the configured dirs.
