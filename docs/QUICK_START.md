# Quick Start — Project Aurora

Get from zero to a full notification strategy in a few commands. Assumes you have completed
[INSTALLATION.md](INSTALLATION.md) (Ollama running, `llama3.2:3b` pulled, `pandas`/`requests`
installed).

All commands are run from the `codebase/` directory:
```bash
cd codebase
```

---

## 1. Run the Whole Thing (Phase 1)

```bash
python main.py
```
This runs the `all` alias = **Task 1 + Task 2** and writes all nine artifacts to
`iteration_0_before_learning/`. (The learning step is *not* included — it needs
`experiment_results.csv`.)

Then run the learning phase:
```bash
python main.py --steps task3
```
This reads `experiment_results.csv` and writes the evolved strategy to
`iteration_1_after_learning/` plus `learning_delta_report.csv` at the repo root.

---

## 2. Run by Task

```bash
python main.py --steps task1     # north_star, features, tone_matrix, segments, goals
python main.py --steps task2     # themes, templates, timing, schedule
python main.py --steps task3     # learning engine (needs experiment_results.csv)
```
Task 2 assumes Task 1's outputs already exist in `iteration_0_before_learning/` (they are
loaded from disk if not in memory).

---

## 3. Run a Single Step

```bash
python main.py --steps north_star
python main.py --steps segments
python main.py --steps templates
```
Multiple steps in order:
```bash
python main.py --steps segments goals
```
Because each step caches to disk, you can re-run just the step you're iterating on.

---

## 4. Useful Flags

| Flag | Effect | Example |
|------|--------|---------|
| `--steps STEP [STEP ...]` | Which steps/aliases to run (default: `all`) | `--steps themes templates` |
| `--data CSV` | Use a custom behavioral CSV | `--data ../my_users.csv` |
| `--out0 DIR` | Override the Task 1/2 output directory | `--out0 ../run2` |
| `--list` | Print all steps and aliases, then exit | `--list` |

---

## 5. Typical Workflows

### First-time full run
```bash
python main.py --list                 # see what's available
python main.py                        # generate iteration_0 (Task 1 + 2)
# ... a real campaign runs, producing experiment_results.csv ...
python main.py --steps task3          # generate iteration_1 (learning)
```

### Iterating on message copy only
```bash
python main.py --steps templates      # re-generate just message_templates.csv
```

### Running on a new company (domain swap)
```bash
# 1. Replace knowledge_bank.md with the new company's KB
# 2. Replace user_behavioral_data.csv with their data (keep the schema; feature_* cols can differ)
python main.py                        # everything re-purposes automatically
```

### Custom data file
```bash
python main.py --data /path/to/your_data.csv
```

---

## 6. What to Expect on the Console

- `[data]` lines — rows loaded, lifecycle-stage distribution, feature columns discovered.
- `[kb]` — KB size loaded.
- Per-step banners (`STEP: NORTH_STAR`, etc.) with progress like `[1/6]`, `[L1]/[L2]/[L3]`,
  `[Pass 1/2]`, `[1/25] ✓ SEG_01 | ...`.
- `[saved]` lines pointing at the output files.
- A final summary block listing any failed steps (failed steps do not stop the run).

> **If you hit a terminal timeout**, just re-run that step — completed steps are already
> persisted to disk, and the orchestrator will reload them.

---

## 7. Where the Outputs Land

| Phase | Directory |
|-------|-----------|
| Task 1 + Task 2 | `iteration_0_before_learning/` |
| Task 3 (learning) | `iteration_1_after_learning/` |
| Learning audit trail | `learning_delta_report.csv` (repo root) |

See [DATA_FORMATS.md](DATA_FORMATS.md) for the exact schema of every file.
