# llm.py
# ─────────────────────────────────────────────────────────────
# Thin wrapper around the local Ollama /api/generate endpoint.
# All generators import from here — swap the model once in config.
# ─────────────────────────────────────────────────────────────

import json
import os
import re
import requests
import pandas as pd

from config import GEN_MODEL, OLLAMA_URL


# ── Core LLM call ─────────────────────────────────────────────

def llm(system: str, prompt: str, temperature: float = 0.3) -> str:
    """
    Send a prompt to Ollama and return the raw text response.
    Raises on HTTP errors so callers know immediately if Ollama is down.
    """
    payload = {
        "model": GEN_MODEL,
        "prompt": f"[SYSTEM]\n{system}\n\n[USER]\n{prompt}",
        "stream": False,
        "options": {"temperature": temperature},
    }
    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json=payload,
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


# ── JSON parsing helpers ──────────────────────────────────────

def parse_json(raw: str):
    """
    Robustly extract a JSON object or array from an LLM response.
    Strips markdown fences, finds the first { or [ and parses from there.
    """
    # Strip markdown code fences
    clean = re.sub(r"```(?:json)?|```", "", raw).strip()

    # Find the first JSON-start character
    brace = clean.find("{")
    bracket = clean.find("[")

    candidates = [x for x in [brace, bracket] if x != -1]
    if not candidates:
        raise ValueError(f"No JSON found in LLM response:\n{raw[:300]}")

    start = min(candidates)
    clean = clean[start:]
    return json.loads(clean)


def safe_parse_json(raw: str, fallback):
    """parse_json but returns `fallback` on any error instead of raising."""
    try:
        return parse_json(raw)
    except Exception as e:
        print(f"  [warn] JSON parse failed: {e} | raw[:200]: {raw[:200]}")
        return fallback


# ── File-saving helpers ───────────────────────────────────────

def save_json(data, filename: str, output_dir: str = None) -> str:
    """Serialise `data` to JSON and save under output_dir."""
    from config import OUTPUT_DIR_0
    out = output_dir or OUTPUT_DIR_0
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  [saved] {path}")
    return path


def save_csv(df: pd.DataFrame, filename: str, output_dir: str = None) -> str:
    """Save a DataFrame as CSV under output_dir."""
    from config import OUTPUT_DIR_0
    out = output_dir or OUTPUT_DIR_0
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, filename)
    df.to_csv(path, index=False)
    print(f"  [saved] {path}")
    return path
