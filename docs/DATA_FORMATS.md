# Data Formats — Project Aurora

Exact schemas for every input and output. Fields are described with type and meaning, with a
real sample row where useful.

---

## INPUTS

### `user_behavioral_data.csv` — per-user activity (Task 1 input)

Required columns (`data_loader.REQUIRED_COLUMNS`) plus any number of `feature_*` boolean
columns (auto-discovered).

| Column | Type | Description |
|--------|------|-------------|
| `user_id` | str | Unique user identifier (e.g. `US_1`) |
| `lifecycle_stage` | str | One of `trial`, `paid`, `churned`, `inactive` (lowercased on load) |
| `days_since_signup` | int | Days since the user registered |
| `age_band` | str | e.g. `25-34` |
| `region` | str | e.g. `tier2` |
| `sessions_last_7d` | int | Sessions in the last 7 days |
| `exercises_completed_7d` | int | Exercises completed in the last 7 days |
| `streak_current` | int | Current daily streak length |
| `coins_balance` | float | In-app currency balance |
| `preferred_hour` | int | Preferred engagement hour (0–23) |
| `notif_open_rate_30d` | float | 30-day notification open rate (0–1) |
| `motivation_score` | float | Composite motivation signal (0–1) |
| `feature_*` | bool | One per product feature (TRUE/FALSE/1/0). Names are free-form. |

**Sample:**
```
US_1,paid,119,25-34,tier2,5,16,22,453,FALSE,FALSE,TRUE,7,0.304,0.65
```
Feature columns in the demo data: `feature_ai_tutor_used`, `feature_leaderboard_viewed`,
`feature_progress_checked`.

**Derived at load time** (added by `add_derived_signals`, not in the CSV):
`activeness_score`, `churn_risk_score`, `propensity_<feature>` (one per feature),
and later `dominant_propensity`, `dominant_propensity_score`, `activeness_band`.

---

### `knowledge_bank.md` / `speakx_kb.txt` — company KB (Task 1 input)

Plain markdown/text. Injected whole into prompts. Sections the pipeline specifically looks
for:
- **North Star Metric** — a heading or `Primary North Star: <metric>` line (used by
  `gen_north_star` L1).
- **Ethical Communication Guidelines** / **Allowed tones / Disallowed tones** — used by
  `gen_tone_hook_matrix` Pass 1.
- Company overview, features, lifecycle, pricing, brand voice — general grounding.

`config.KB_PATH` points at `knowledge_bank.md` by default.

---

### `experiment_results.csv` — performance feedback (Task 3 input)

Real-world outcomes per template. The learning engine normalizes several schema variants
(`_normalise_experiment_results_schema`) and can backfill `ctr`/`engagement_rate` from
`total_opens`/`total_engagements`/`total_sends`.

| Column | Type | Description |
|--------|------|-------------|
| `template_id` | str | Matches an Iteration 0 template (aliases: `template`, `message_template_id`) |
| `segment_id` | str | Segment code (aliases: `segment`, `segment_code`) |
| `segment_name` | str | Human-readable segment name |
| `lifecycle_stage` | str | trial/paid/churned/inactive |
| `phase_name` | str | Lifecycle phase |
| `goal` | str | Primary goal (aliased to `primary_goal`) |
| `theme` | str | Octalysis theme used |
| `notification_window` | str | Delivery window (aliases: `time_window`, `recommended_time_window`) |
| `total_sends` | int | Messages sent |
| `total_opens` | int | Opens |
| `total_engagements` | int | Engagements |
| `ctr` | float | Click-through rate (0–1) |
| `engagement_rate` | float | Engagement rate (0–1) |
| `uninstall_rate` | float | Uninstall rate (0–1) |

**Sample:**
```
TPL_SEG_01_PREMIUM_AFFIRMATION_01,SEG_01,High-Active Power Users,paid,Premium Affirmation,Increase exercise completion rate by 20%,Epic Meaning,evening,5000,1050,2850,0.2100,0.5700,0.0060
```

**Classification** (`TEMPLATE_THRESHOLDS`): GOOD ≥ (ctr 0.15, eng 0.40); NEUTRAL ≥ (0.05,
0.20); else BAD.

---

## TASK 1 OUTPUTS → `iteration_0_before_learning/`

### `company_north_star.json`
```jsonc
{
  "company": "SpeakX",
  "inferred_north_star": {
    "metric_name": "Monthly Retention",
    "how_it_was_determined": "explicit_extraction",   // or "scored_inference"
    "definition": "...",
    "justification": "...",
    "measurable_proxy": "(converters completing ≥1 exercise) / (total trial) × 100"
  },
  "supporting_metrics": [ { "name": "...", "definition": "...", "why_it_matters": "..." } ],
  "lifecycle_stages": [ { "stage": "trial", "day_range": "D0-D7", "primary_goal": "..." } ],
  "generated_at": "2026-03-07",
  "iteration": 0
}
```

### `feature_goal_map.json`
```jsonc
{
  "feature_goal_map": [
    {
      "feature": "Sia — AI Speaking Partner",
      "feature_id": "feat_001",
      "description": "...",
      "lifecycle_stage": ["inactive", "paid", "trial"],
      "primary_goal": "...",
      "sub_goals": ["...", "..."],
      "north_star_contribution": "Increase W1 Retention by 10%",
      "propensity_levers": ["loss avoidance", "social influence"],
      "expected_outcome": "Average user completes ≥4 sessions/week"
    }
  ],
  "generated_at": "2026-03-07",
  "iteration": 0
}
```

### `allowed_tone_hook_matrix.json`
```jsonc
{
  "allowed_tones":    ["Motivational", "Encouraging", ...],     // KB-extracted flat list
  "disallowed_tones": ["Shaming", "Aggressive sales pressure", ...],
  "hook_taxonomy": [
    { "core_drive": "Epic Meaning", "application": "<KB-grounded sentence>",
      "example_phrases": ["<English>", "<Hindi>"] }
    // ...one per Octalysis drive (8 total)
  ],
  "matrix": [
    { "lifecycle_stage": "trial",
      "allowed_tones": [...], "disallowed_tones": [...],
      "primary_drives": ["Scarcity", "Empowerment", "Accomplishment"],
      "secondary_drives": ["Epic Meaning", "Unpredictability"],
      "hook_intensity": "high", "tone_rationale": "..." }
    // ...one per lifecycle stage
  ],
  "source": "KB Ethical Communication Guidelines",
  "bilingual_note": "All messages must be available in Hindi and English",
  "generated_at": "<today>", "iteration": 0
}
```

### `user_segments.csv` — one row per user
| Column | Description |
|--------|-------------|
| `segment_id` | `SEG_01`…`SEG_14` |
| `segment_name` | Human-readable name |
| `user_id` | User id |
| `lifecycle_stage` | trial/paid/churned/inactive |
| `age_band`, `region` | Demographics |
| `activeness_score` | RFM composite (0–1) |
| `churn_risk_score` | Churn risk (0–1) |
| `activeness_band` | `low` / `moderate` / `high` (percentile cut) |
| `dominant_propensity` | Highest-propensity feature name |
| `dominant_propensity_score` | Its score (0–1) |

**The 14 segments** (`SEGMENT_NAMES`): SEG_01 High-Active Power Users, SEG_02 High-Active
Streak Keepers, SEG_03 High-Active Trial Converters, SEG_04 Moderate-Active Feature
Enthusiasts, SEG_05 Moderate-Active Casual Paid, SEG_06 Moderate-Active Trial Activators,
SEG_07 Moderate-Active Trial Fence-Sitters, SEG_08 Low-Active At-Risk Paid, SEG_09 Low-Active
Cold Trial, SEG_10 Recent Churned, SEG_11 Deep Churned, SEG_12 Inactive High-Propensity,
SEG_13 Inactive Low-Propensity, SEG_14 Unclassified.

*(A richer per-segment summary DataFrame is produced in-memory with drives, tones, strategy,
and per-feature propensity averages — see `SEGMENT_META`.)*

### `segment_goals.csv` — one row per segment × phase (11-phase model)
Saved columns: `segment_id`, `segment_name`, `dominant_propensity`, `lifecycle_stage`,
`phase_number`, `phase_name`, `day_range`, `primary_goal`, `sub_goal_1`, `sub_goal_2`,
`sub_goal_3`.
*(The generator internally builds more fields — day-level focus, octolysis drive, hook
template, success/failure/escalation signals, personalization lever, segment stats — but only
the columns above are written to CSV.)*

**The 11 phases** (`PHASE_CONFIG`): Trial → (1) Activation & Value Discovery, (2) Habit
Formation, (3) Conversion Push; Paid → (4) Premium Affirmation, (5) Deep Immersion, (6) Social
& Expansion, (7) Overcoming the Slump, (8) ROI Demonstration, (9) Retention & Renewal; Churned
→ (10) Win-Back; Inactive → (11) Low-Friction Re-engagement.

---

## TASK 2 OUTPUTS → `iteration_0_before_learning/`

### `communication_themes.csv` — one row per segment × phase
| Column | Description |
|--------|-------------|
| `segment_id`, `segment_name` | Segment |
| `lifecycle_stage`, `phase_number`, `phase_name`, `day_range` | Phase context |
| `primary_goal` | Goal for this segment × phase |
| `primary_theme`, `secondary_theme` | Octalysis drive names (validated against the 8 drives) |
| `tone_preference` | One of the allowed tones |
| `hook_en`, `hook_hi` | Bilingual hook phrases |

### `message_templates.csv` — **5 rows per segment × phase**
| Column | Description |
|--------|-------------|
| `template_id` | `TPL_<segment>_<PHASE>_<NN>` |
| `segment_id`, `segment_name`, `lifecycle_stage` | Identity |
| `phase_number`, `phase_name`, `day_range` | Phase |
| `primary_goal`, `theme`, `tone` | Strategy |
| `title_en`, `body_en`, `cta_en` | English copy |
| `title_hi`, `body_hi`, `cta_hi` | Hindi/Hinglish copy (transcreated) |
| `hook_type` | Octalysis drive (distinct across the 5) |
| `format_type` | Archetype: `direct_cta`, `question_hook`, `social_proof`, `insight_tip`, `challenge` |
| `feature_ref` | Referenced product feature |
| `iteration` | `0` |

### `timing_recommendations.csv` — one row per segment × recommended window
| Column | Description |
|--------|-------------|
| `segment_id`, `segment_name` | Segment |
| `recommended_time_window` | One of the 6 windows |
| `expected_ctr`, `expected_engagement` | Scaled from segment activeness, with rank decay |
| `rationale` | Why this window/rank |

**The 6 windows** (`TIME_WINDOWS`): `early_morning` (06–09), `mid_morning` (09–12),
`afternoon` (12–15), `late_afternoon` (15–18), `evening` (18–21), `night` (21–24).

### `user_notification_schedule.csv` — **wide format**, one row per segment × lifecycle-day
| Column | Description |
|--------|-------------|
| `segment_id`, `segment_name`, `lifecycle_stage` | Segment |
| `lifecycle_day` | e.g. `D8` |
| `notif_1` … `notif_9` | Each a `(template_id, time_window, channel)` tuple string, or empty |

**Sample cell:** `(TPL_SEG_01_PREMIUM_AFFIRMATION_05, evening, push_notification)`
Channels: `push_notification`, `in_app_message`, `email` (mix varies by activeness). Daily
frequency (# of populated notif columns) is 8/5/3 by segment activeness.

---

## TASK 3 OUTPUTS → `iteration_1_after_learning/` + root

Iteration 1 re-emits `message_templates.csv`, `timing_recommendations.csv`, and
`user_notification_schedule.csv` (same schemas as above, with `iteration=1` on templates and
evolved content). Rewritten BAD templates get a `_v2` `template_id` and a `source_template_id`
column preserving A/B lineage. `user_segments.csv` is copied through unchanged when absent.

### `learning_delta_report.csv` — audit trail (written to repo root)
One row per change made by the learning engine.
| Column | Description |
|--------|-------------|
| `entity_type` | `template` / `segment` |
| `entity_id` | Template id or segment id |
| `change_type` | `template_replacement`, `template_iteration`, `timing_shift`, `frequency_reduction` |
| `metric_trigger` | What triggered it (e.g. `poor_performance_suppression: CTR=…, ER=…`) |
| `before_value` | Prior state |
| `after_value` | New state |
| `explanation` | Causal reasoning (often the LLM's `improvement_rationale`) |
| `timestamp` | `YYYY-MM-DD HH:MM:SS` |
