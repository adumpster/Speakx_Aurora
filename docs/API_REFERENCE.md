# API Reference — Project Aurora

Function-level reference for every public entry point, grouped by module. Signatures are
given as they appear in the source. All modules live under `codebase/`.

---

## `config.py` — Constants

Not functions — module-level constants imported across the codebase.

| Name | Type | Description |
|------|------|-------------|
| `OLLAMA_URL` | `str` | Ollama base URL (`http://localhost:11434`) |
| `GEN_MODEL` | `str` | Generation model id (`llama3.2:3b`) |
| `BASE_DIR` | `Path` | Project root (config's grandparent dir) |
| `KB_PATH` | `str` | Path to the Knowledge Bank file |
| `USER_DATA_PATH` | `str` | Default behavioral CSV path |
| `OUTPUT_DIR` / `OUTPUT_DIR_0` | `str` | Task 1/2 output dir (`iteration_0_before_learning`) |
| `OUTPUT_DIR_1` | `str` | Task 3 output dir (`iteration_1_after_learning`) |
| `EXPERIMENT_RESULTS_PATH` | `str` | Default path to `experiment_results.csv` |
| `KB_MAX_CHARS` | `int` | Max KB chars per prompt (`4000`) |
| `OCTOLYSIS_DRIVES` | `list[dict]` | 8 core drives: `{id, name, example, hook}` |
| `TIME_WINDOWS` | `list[dict]` | 6 windows: `{name, range, start, end, use}` |
| `FREQ_BANDS` | `list[dict]` | Activeness → notifs/day bands |
| `GUARDRAIL_UNINSTALL_RATE` | `float` | `0.02` uninstall guardrail |
| `TEMPLATE_THRESHOLDS` | `dict` | GOOD/NEUTRAL/BAD CTR & engagement cutoffs |
| `LIFECYCLE_STAGES` | `dict` | trial/paid/churned/inactive definitions |

---

## `llm.py` — LLM Wrapper & Helpers

### `llm(system, prompt, temperature=0.3, timeout=360) -> str`
Posts to Ollama's `/api/generate` and returns the raw `response` text. Builds the payload as
`[SYSTEM]\n{system}\n\n[USER]\n{prompt}` with `stream=False`. Raises on HTTP errors so callers
learn immediately if Ollama is down. `timeout` is in seconds.

### `parse_json(raw) -> dict | list`
Robustly extracts JSON from a model response. Strips markdown fences, finds the first `{`/`[`,
then tries three tiers: (1) standard `json.loads`, (2) fix literal control chars + invalid
escapes, (3) regex field extraction for flat objects. Raises `ValueError` if all fail.

### `safe_parse_json(raw, fallback) -> Any`
Calls `parse_json`; on **any** exception prints a warning and returns `fallback`.

### `save_json(data, filename, output_dir=None) -> str`
Serializes `data` to pretty JSON (`indent=2, ensure_ascii=False`) under `output_dir`
(defaults to `OUTPUT_DIR_0`). Creates the dir. Returns the path.

### `save_csv(df, filename, output_dir=None) -> str`
Writes `df` to CSV (`index=False`) under `output_dir`. Returns the path.

*Internal helpers:* `_fix_invalid_escapes`, `_fix_literal_control_chars`, `_extract_fields_regex`.

---

## `kb_loader.py` — Knowledge Bank

### `load_kb(path=KB_PATH) -> str`
Reads and caches the KB file (module-level cache — read once). Returns `""` with a warning if
missing (graceful degradation).

### `get_kb_section(heading, path=KB_PATH) -> str`
Extracts a markdown section by heading substring (case-insensitive). Returns the full KB if
the heading isn't found (nothing is lost).

### `build_context(data_summary, path=KB_PATH) -> str`
**The main function every generator calls.** Returns a single string =
`[full KB text] + [behavioral data summary]`, so the LLM reasons from company knowledge *and*
real user numbers at once.

---

## `data_loader.py` — Data Pipeline

### `@dataclass DataProfile`
Bundle passed to generators:
| Field | Type | Meaning |
|-------|------|---------|
| `df` | `pd.DataFrame` | Cleaned + scored data |
| `feature_cols` | `list` | Discovered `feature_*` column names |
| `lifecycle_stages` | `list` | Unique lifecycle stage values |
| `summary` | `str` | Text block injected into prompts |

### `load_data(path=USER_DATA_PATH) -> pd.DataFrame`
Reads the CSV, warns on missing `REQUIRED_COLUMNS`, normalizes `feature_*` booleans
(TRUE/1/FALSE/0 → bool), coerces `FLOAT_COLUMNS`/`INT_COLUMNS`, lowercases `lifecycle_stage`.

### `add_derived_signals(df) -> pd.DataFrame`
Adds computed columns (returns a copy):
- `activeness_score` = `0.30·R + 0.40·F + 0.30·M` (RFM composite, 0–1).
- `churn_risk_score` = weighted inactive/low-session/low-streak/low-open signals (0–1).
- `propensity_<feature>` for **every** `feature_*` col = `0.6·usage + 0.4·motivation`.
- Fallback `propensity_engagement` if no feature columns exist.

### `build_data_summary(df) -> str`
Compact text summary (totals, stage/age/region distributions, activity averages, per-feature
usage %, per-stage averages) injected as prompt grounding.

### `extract_features(df) -> list[dict]`
One dict per `feature_*` column: `{column, name, lifecycle_stages, usage_rate, usage_pct, user_count}`.

### `load_and_profile(path=USER_DATA_PATH) -> DataProfile`
**Single entry point** used by all generators: load → clean → derive → summarize → return a
`DataProfile`.

---

## Task 1 Generators

### `gen_north_star.py`
**`gen_north_star(profile, output_dir=None) -> dict`**
3-layer approach: **L1** try explicit KB extraction; **L2** if not explicit, structured
scoring of candidate metrics; **L3** build the full structured JSON. Saves
`company_north_star.json`. *(Helper: `_unwrap` normalizes list→dict.)*

### `gen_feature_goal_map.py`
**`gen_feature_goal_map(profile, north_star, output_dir=None) -> dict`**
Discovers features from `profile.feature_cols`, makes **one LLM call per feature** to build a
goal-mapping entry, saves `feature_goal_map.json`.
*(Helpers: `_extract_features`, `_gen_feature_entry`.)*

### `gen_tone_hook_matrix.py`
**`gen_tone_hook_matrix(profile=None, output_dir=None) -> dict`**
Two-pass: **Pass 1** extract allowed/disallowed tones from the KB; **Pass 2** build the
8-drive `hook_taxonomy` + per-lifecycle `matrix`. Validates all 8 drives and all stages are
present, patching with defaults. Saves `allowed_tone_hook_matrix.json`.
*(Helpers: `_pass1_extract_tones`, `_pass2_build_taxonomy_and_matrix`, `_default_hook_taxonomy`, `_default_stage_entry`.)*

### `segmentation_engine.py` *(no LLM)*
**`gen_user_segments(df=None, output_dir=None) -> (user_seg_df, seg_summary_df)`**
Deterministic MECE segmentation. Computes dominant propensity per user, percentile-based
activeness bands (33rd/67th), assigns one of 14 segments, and emits both a per-user CSV
(`user_segments.csv`) and an in-memory per-segment summary DataFrame.
*(Helpers: `_get_propensity_cols`, `_dominant_propensity`, `_add_dominant_propensity`,
`_compute_percentile_bands`, `_assign_segment`, `_key_signal`. Constants: `SEGMENT_META`,
`SEGMENT_NAMES`.)*

### `goal_builder.py`
**`gen_segment_goals(user_segments_df=None, df=None, north_star=None, output_dir=None, feature_goal_map=None, tone_matrix=None) -> pd.DataFrame`**
Builds `segment_goals.csv` across the **11-phase** lifecycle model. Merges the static
`PHASE_CONFIG` scaffold with runtime-derived Octalysis drives (from tone matrix) and feature
nudges (from feature map); makes **one LLM call per segment × phase**. Saves
`segment_goals.csv`.
*(Helpers: `_index_tone_matrix`, `_drives_for_lifecycle`, `_derive_feature_nudges`,
`_load_feature_goal_map`, `_load_tone_matrix`, `_build_phase_goal`, `safe_parse_json`, `_call_llm`.
Constants: `PHASE_CONFIG`, `LIFECYCLE_PHASE_MAP`.)*

---

## Task 2 Generators

### `comm_themes.py`
**`gen_communication_themes(user_segments_df=None, segment_goals_df=None, tone_hook_matrix=None, df=None, output_dir=None, max_workers=2) -> pd.DataFrame`**
One row per segment × phase. Extracts valid tones (from matrix) and valid themes (from
`OCTOLYSIS_DRIVES`), aggregates behavioral stats per segment, then runs concurrent LLM calls
(`ThreadPoolExecutor`) to pick primary/secondary theme + tone and write EN/HI hooks. Hard-enforces
valid values post-parse. Saves `communication_themes.csv`.
*(Helper: `_gen_theme_entry`.)*

### `message_template_gen.py`
**`gen_message_templates(themes_df=None, goals_df=None, user_segments_df=None, df=None, feature_goal_map=None, output_dir=None, max_workers=2) -> pd.DataFrame`**
Generates **exactly 5 templates per segment × phase** (`TEMPLATES_PER_COMBO=5`). Assigns each
of the 5 a distinct message-format archetype (`MESSAGE_FORMATS`) and requires a distinct
Octalysis hook per template. Retries up to `MAX_RETRIES=3`; pads with fallback rows if short.
Transcreates Hindi (not literal translation). Concurrent. Saves `message_templates.csv`.
*(Helpers: `_gen_templates_for_combo`, `_worker`, `_resolve_feature_ref`, `_load_feature_map`,
`_unwrap_list`, `_make_template_id`, `_fallback_row`, `_formats_reference`, `_drives_reference`.)*

### `timing_optimizer.py` *(no LLM)*
**`gen_timing_recommendations(user_seg_df, raw_df, output_dir=None) -> pd.DataFrame`**
Maps each user's `preferred_hour` to a standard window, then per segment picks the top-N
windows (N by activeness band: high=3, moderate=2, low/churned/inactive=1) and computes
expected CTR/engagement with rank decay. Saves `timing_recommendations.csv`.

**`gen_user_notification_schedule(user_seg_df, templates_df, timing_df, _raw_df, output_dir=None) -> pd.DataFrame`**
A per-user (long-format) schedule builder assigning windows + templates. *(Note: the pipeline's
`schedule` step actually calls `notification_scheduler.run_pipeline()`, which produces the
wide-format schedule; this function is an alternative long-format builder.)*

**`map_hour_to_window(hour) -> str`** — maps an int hour (0–23) to one of the 6 windows.

### `notification_scheduler.py` *(no LLM)*
**`run_pipeline() -> None`**
The `schedule` step. Reads segments, timing, templates, and goals; sanitizes segment IDs;
computes per-segment daily frequency (8/5/3 by activeness); aligns templates to phases by
parsing template IDs; expands the segment curriculum into a day grid; and writes the
**wide-format** `user_notification_schedule.csv` (`notif_1`…`notif_9`, each a
`(template_id, time_window, channel)` tuple). Channel mix (push/in-app/email) varies by
activeness.
*(Helpers: `resolve_file`. Constants: `INPUT_*`, `OUTPUT_*`, `ALL_WINDOWS`.)*

---

## Task 3 — `learning_engine.py`

### `run_learning_engine(iter0_dir=OUTPUT_DIR_0, experiment_path=None, iter1_dir=OUTPUT_DIR_1) -> (iter1_templates_df, delta_df)`
Main 5-phase orchestrator. Tolerates `main.py`'s call convention
`run_learning_engine(templates_csv_path, timing_csv_path, OUTPUT_DIR_1)` — it detects whether
the first arg is a file (derives the dir) and whether the second arg is a timing CSV vs. an
experiment CSV, resolving `experiment_results.csv` from standard locations if needed. Writes
iteration-1 templates, timing, and schedule, plus `learning_delta_report.csv`.

**Phase functions:**
| Function | Phase | Kind |
|----------|-------|------|
| `load_and_classify_experiments(path) -> df` | P1 | deterministic |
| `evaluate_segment_guardrails(exp_df) -> dict` | P1 | deterministic (send-weighted uninstall) |
| `aggregate_timing_performance(exp_df) -> df` | P1 | deterministic (combined_score) |
| `resolve_timing(iter0_timing_path, timing_perf, delta_rows) -> df` | P2 | deterministic |
| `evolve_templates(iter0_templates, exp_df, delta_rows) -> df` | P3 | hybrid |
| `regenerate_schedule(iter0_schedule_path, iter1_templates, iter1_timing, guardrails, delta_rows, output_dir) -> df` | P4 | deterministic |
| `_delta_row(...) -> dict` | P5 | helper (audit row) |

**LLM rewrite helpers:** `_rewrite_bad_template(original_row, new_theme, good_refs) -> dict`,
`_iterate_neutral_template(original_row, good_refs) -> dict`.

**Variety/creativity helpers:** `_get_creative_angle(segment_id)`,
`_identify_replacement_theme(failed_theme, segment_id, exp_df)`.

**Schema/parse helpers:** `_normalise_experiment_results_schema`, `_resolve_row_goal`,
`_parse_notif_cell`, `_pack_notif_cell`. **Constants:** `THEME_POOL`, `SEGMENT_ANGLES`,
`_EXPERIMENT_COLUMN_ALIASES`.

---

## `main.py` — Orchestrator

### `main() -> None`
Parses CLI args (`--steps`, `--data`, `--out0`, `--list`), loads the `DataProfile` once,
resolves steps via `resolve_steps`, and runs each with fault isolation.

### `run_step(name, profile, out0) -> None`
Dispatch table mapping a step name to its generator; stores results in the module `state` dict
and reads upstream artifacts from `state` or disk.

### `resolve_steps(requested) -> list`
Expands aliases (`task1/task2/task3/all`) into canonical steps, de-duplicated and order-preserving.

*(Helpers: `_df_or_load`, `_load_json`, `_load_csv`. Constants: `STEPS`, `ALIASES`, `state`.)*

---

## Programmatic Usage Example

```python
import sys; sys.path.insert(0, "codebase")
from data_loader import load_and_profile
from gen_north_star import gen_north_star
from gen_feature_goal_map import gen_feature_goal_map
from segmentation_engine import gen_user_segments

profile = load_and_profile("user_behavioral_data.csv")

ns  = gen_north_star(profile, "iteration_0_before_learning")
fgm = gen_feature_goal_map(profile, ns, "iteration_0_before_learning")
user_seg_df, seg_summary_df = gen_user_segments(profile.df, "iteration_0_before_learning")
```
