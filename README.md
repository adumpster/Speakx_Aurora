# Project Aurora — Documentation

**Self-Learning Notification Orchestrator** · SpeakX / KRITI 2026

Project Aurora turns a company Knowledge Bank + a user behavioral CSV into a complete,
personalized, bilingual push-notification strategy — then learns from real campaign
performance and rewrites its own outputs to improve the next run. It is domain-agnostic and
runs fully offline on a local Ollama model.

---

## Documentation Index

| Document | Read it for… |
|----------|--------------|
| [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) | What Aurora is, the two phases, core principles |
| [INSTALLATION.md](INSTALLATION.md) | Prerequisites, Ollama + Python setup, troubleshooting |
| [QUICK_START.md](QUICK_START.md) | Commands, workflows, flags, expected console output |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Data flow, deterministic-vs-LLM split, the learning engine |
| [APP_STRUCTURE.md](APP_STRUCTURE.md) | Repo layout, module responsibilities, dependency graph |
| [API_REFERENCE.md](API_REFERENCE.md) | Every public function, signature, and constant |
| [DATA_FORMATS.md](DATA_FORMATS.md) | Exact schema of every input and output file |
| [MODELS_DOCUMENTATION.md](MODELS_DOCUMENTATION.md) | The LLM backend, prompting, JSON parsing, reliability |
| [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) | The whole build in one read |

---

## 30-Second Start

```bash
# 1. Install Ollama (https://ollama.com), then:
ollama pull llama3.2:3b
pip install pandas numpy requests

# 2. Generate the baseline strategy (Task 1 + Task 2):
cd codebase
python main.py

# 3. Learn from real results (Task 3):
python main.py --steps task3
```

Outputs land in `iteration_0_before_learning/` and `iteration_1_after_learning/`, plus
`learning_delta_report.csv` at the repo root.

---

## The Pipeline in One Table

| Task | Steps | Output dir |
|------|-------|-----------|
| **1 — Foundational Intelligence** | north_star · features · tone_matrix · segments · goals | `iteration_0_before_learning/` |
| **2 — Communication Generation** | themes · templates · timing · schedule | `iteration_0_before_learning/` |
| **3 — Self-Learning** | learning (5 internal phases) | `iteration_1_after_learning/` + delta report |

Built with a deliberate split: **deterministic Python** for scoring, segmentation, timing,
scheduling, and guardrails; a **local LLM** only for strategy and copy — each with a coded
fallback so the pipeline never hard-fails.
