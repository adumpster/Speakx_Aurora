# Installation Guide — Project Aurora

Project Aurora runs entirely on your machine. There are no cloud API keys — text generation
uses a **local Ollama model**.

---

## 1. Prerequisites

| Requirement | Version / Notes |
|-------------|-----------------|
| Python | 3.10+ (uses `X \| Y` type unions and `list[dict]` syntax) |
| Ollama | Latest — provides the local LLM runtime |
| Disk | ~3–4 GB free for the `llama3.2:3b` model |
| RAM | 8 GB recommended for the 3B model |
| OS | Windows / macOS / Linux (developed on Windows 11) |

---

## 2. Step-by-Step Setup

### Step 1 — Install Ollama
Download and install from **https://ollama.com**.

Verify it is running:
```bash
ollama --version
```
By default Ollama serves on `http://localhost:11434`, which matches `OLLAMA_URL` in
`config.py`.

### Step 2 — Pull the generation model
```bash
ollama pull llama3.2:3b
```
This is the default `GEN_MODEL`. You can swap it for any Ollama model (see
[MODELS_DOCUMENTATION.md](MODELS_DOCUMENTATION.md)).

### Step 3 — Install Python dependencies
The project depends on just two third-party packages:
```bash
pip install pandas requests
```
`numpy` ships as a pandas dependency and is imported directly by a few modules; if it is not
present, install it explicitly:
```bash
pip install pandas numpy requests
```

> There is no `requirements.txt` in the repo. The full dependency set is:
> `pandas`, `numpy`, `requests` (plus the Python standard library:
> `argparse`, `os`, `sys`, `json`, `re`, `shutil`, `datetime`, `pathlib`,
> `dataclasses`, `concurrent.futures`, `logging`, `typing`).

### Step 4 — Confirm the working files exist
From the project root, make sure these inputs are present:
- `knowledge_bank.md` (the KB — `KB_PATH` points here)
- `user_behavioral_data.csv` (the behavioral input)
- `experiment_results.csv` (only needed for Task 3 / the learning step)

---

## 3. Verifying the Installation

Run the orchestrator's list command from inside `codebase/`:
```bash
cd codebase
python main.py --list
```
You should see the 10 steps and 4 aliases printed. Then run a single lightweight step to
confirm the full stack (data loader + KB + Ollama) works end-to-end:
```bash
python main.py --steps north_star
```
Expected: console logs showing the KB loaded, the data profile, three LLM layers (L1/L2/L3),
and finally `[saved] .../company_north_star.json`.

---

## 4. Configuration

All settings live in `codebase/config.py`. The most common changes:

| Setting | Default | Change when… |
|---------|---------|--------------|
| `GEN_MODEL` | `"llama3.2:3b"` | You want a different/larger local model |
| `OLLAMA_URL` | `"http://localhost:11434"` | Ollama runs on another host/port |
| `KB_PATH` | `<root>/knowledge_bank.md` | Your KB lives elsewhere / you use `speakx_kb.txt` |
| `USER_DATA_PATH` | `<root>/user_behavioral_data.csv` | Default behavioral CSV path |
| `KB_MAX_CHARS` | `4000` | Your model supports a bigger context window |

Paths are resolved relative to the **project root** (`BASE_DIR = config.py's parent's
parent`), so outputs land in `iteration_0_before_learning/` and
`iteration_1_after_learning/` at the repo top level regardless of where you launch Python
from.

---

## 5. Troubleshooting

| Symptom | Cause & Fix |
|---------|-------------|
| `requests.exceptions.ConnectionError` | Ollama isn't running. Start it / re-check `OLLAMA_URL`. |
| Terminal **timeout** errors | Large prompts on a slow machine. The README's advice: **rerun the step** — outputs from completed steps are cached on disk. You can also raise the `timeout` arg in `llm.llm()`. |
| `[kb] WARNING: KB file not found` | `KB_PATH` is wrong; the pipeline degrades to data-only context. |
| `[warn] Missing expected columns` | Your CSV is missing a `REQUIRED_COLUMNS` field — see [DATA_FORMATS.md](DATA_FORMATS.md). |
| `JSON parse failed` warnings | The local model returned malformed JSON; `safe_parse_json` used the fallback. Usually harmless; rerun for better output or use a stronger model. |
| Model too slow / low quality | Swap `GEN_MODEL` to a larger model and re-pull via `ollama pull`. |
