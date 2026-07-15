# Models & LLM Documentation — Project Aurora

How Project Aurora uses a language model: which model, how it's called, how prompts are
built, how output is parsed, and how the system stays reliable on a small local model.

---

## 1. Model Backend

Aurora uses a **local LLM served by [Ollama](https://ollama.com)** — no cloud API, no keys,
no token cost. Everything runs offline on the developer's machine.

| Setting (in `config.py`) | Default | Meaning |
|--------------------------|---------|---------|
| `GEN_MODEL` | `"llama3.2:3b"` | The generation model (Llama 3.2, 3B params) |
| `OLLAMA_URL` | `"http://localhost:11434"` | Ollama's local HTTP endpoint |

There is a **single generation model** for all text tasks — north star reasoning, feature
mapping, tone extraction, goal design, theme selection, copywriting, and the learning
rewrites. No embedding model is used (see §5, "No RAG").

**Swapping the model:** pull any Ollama model and set `GEN_MODEL`:
```bash
ollama pull qwen2.5:7b       # example: a larger model for higher quality
```
```python
# config.py
GEN_MODEL = "qwen2.5:7b"
```
Larger models generally produce better JSON adherence and richer copy at the cost of speed.

---

## 2. The Call Interface (`llm.py`)

Every generator calls one function:

```python
def llm(system: str, prompt: str, temperature: float = 0.3, timeout: int = 360) -> str
```

It POSTs to Ollama's `/api/generate`:
```jsonc
{
  "model": GEN_MODEL,
  "prompt": "[SYSTEM]\n{system}\n\n[USER]\n{prompt}",
  "stream": false,
  "options": { "temperature": 0.3 }
}
```
- **`temperature=0.3`** by default — low, favoring consistent, well-structured JSON over
  creative divergence. (Callers can raise it, but generators use the default.)
- **`stream=false`** — the full response is returned at once.
- **`timeout=360`s** — large KB-injected prompts on a small local model can be slow; a long
  timeout avoids premature failures. Callers that hit a timeout should simply re-run the step.
- **Raises on HTTP error** — so a down/misconfigured Ollama is reported immediately.

---

## 3. Prompt Construction Pattern

Every generator follows the same shape:

1. **System message** — a terse role + a hard instruction to *"Output ONLY valid JSON — no
   markdown, no explanation."*
2. **Context block** — via `kb_loader.build_context(summary)`: the **full KB text** plus the
   **behavioral data summary**, so the model reasons from company knowledge and real numbers
   at once.
3. **Task-specific instructions** — the concrete ask.
4. **An explicit JSON skeleton** — the exact keys expected, so parsing is predictable.

Some generators use **multi-pass / multi-layer prompting** for reliability on a small model:

| Generator | Strategy |
|-----------|----------|
| `gen_north_star` | **3 layers**: L1 explicit KB extraction → L2 structured metric scoring (fallback) → L3 build full JSON |
| `gen_tone_hook_matrix` | **2 passes**: Pass 1 extract tones → Pass 2 build taxonomy + matrix (splitting keeps each prompt focused) |
| `gen_feature_goal_map` | **One call per feature** — smaller asks parse more reliably |
| `goal_builder` | **One call per segment × phase** |
| `comm_themes` | **One call per segment × phase**, concurrent |
| `message_template_gen` | **One call per segment × phase** for all 5 templates, with retries |

Rationale: many small, tightly-scoped prompts outperform one giant prompt on a 3B model, and
they degrade independently.

---

## 4. Robust JSON Parsing

Small models often wrap JSON in prose or emit minor syntax errors. `llm.parse_json()` handles
this in **three tiers**:

1. **Standard** — strip ```` ```json ```` fences, locate the first `{`/`[`, `json.loads`.
2. **Sanitized** — fix literal control characters inside strings (`\n`, `\t`, `\r`) and escape
   invalid backslash sequences, then re-parse.
3. **Regex extraction** — pull `"key": "value"` pairs directly, tolerating unescaped quotes,
   to recover at least partial data.

`safe_parse_json(raw, fallback)` wraps all of this and returns a caller-supplied `fallback`
on total failure — so **no LLM stage can hard-crash the pipeline**.

---

## 5. Why No RAG / No Embeddings

The KB is ~2,000–4,000 characters. For a document that small, **full injection dominates
retrieval**:
- The model sees the entire business context — nothing is dropped by a retrieval step.
- No vector database, embedding model, chunking, or similarity search to run or maintain.
- `KB_MAX_CHARS` (default 4000) bounds the injected text; raise it for larger-context models.

The KB is read once and cached in-module (`kb_loader._kb_cache`).

---

## 6. Reliability & Cost Engineering

| Concern | Mechanism |
|---------|-----------|
| Malformed JSON | 3-tier `parse_json` + `safe_parse_json` fallbacks |
| Empty/short output | `message_template_gen` retries up to `MAX_RETRIES=3`, then pads with fallback rows |
| Missing all 8 drives / stages | `gen_tone_hook_matrix` validates and patches with `_default_*` |
| Slow local inference | Long `timeout`; concurrency (`ThreadPoolExecutor`, `max_workers=2`) on the two heavy stages; re-run advice on timeout |
| Determinism where needed | Segmentation, timing, scheduling, guardrails are **pure Python** — no model involved |
| Overloading the local model | `max_workers=2` caps parallel Ollama calls |

---

## 7. Temperature & Determinism Notes

- The **LLM stages are not fully deterministic** even at `temperature=0.3` — re-running a
  generator can yield slightly different copy. This is acceptable because outputs are
  validated/constrained post-parse (valid tones, valid themes, valid formats are hard-enforced).
- The **deterministic stages are fully reproducible** — same input CSV ⇒ identical
  `user_segments.csv`, `timing_recommendations.csv`, and schedule.
- The learning engine's **classification, guardrail, and timing logic are deterministic**;
  only the template *rewrites* use the LLM. This keeps the audit trail
  (`learning_delta_report.csv`) trustworthy: what changed and why is decided by rules, and the
  model only supplies the new wording.

---

## 8. Creative-Control Devices in the Learning Engine

To keep LLM rewrites varied and non-repetitive, `learning_engine.py` adds guardrails around
the model:
- **`SEGMENT_ANGLES`** — a rotating list of metaphors per segment (e.g. "cooking metaphor",
  "rocket launch") forced into each rewrite prompt so titles don't converge.
- **`_generated_titles`** — a running set of already-used titles injected as a "DO NOT reuse"
  block.
- **`THEME_POOL` + `_identify_replacement_theme`** — forced theme variety per segment when
  swapping out a BAD template's theme.

These are prompt-engineering scaffolds, not separate models.
