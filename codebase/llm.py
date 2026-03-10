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

def llm(system: str, prompt: str, temperature: float = 0.3, timeout: int = 360) -> str:
    """
    Send a prompt to Ollama and return the raw text response.
    Raises on HTTP errors so callers know immediately if Ollama is down.
    timeout: seconds to wait for a response (default 360 — large prompts need more time).
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
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


# ── JSON parsing helpers ──────────────────────────────────────

def _fix_invalid_escapes(s: str) -> str:
    """Replace backslashes not part of a valid JSON escape sequence with \\\\."""
    # Valid JSON escapes: \", \\, \/, \b, \f, \n, \r, \t, \uXXXX
    return re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', s)


def _fix_literal_control_chars(s: str) -> str:
    """Replace literal newlines/tabs inside JSON string values with their escape equivalents."""
    result = []
    in_string = False
    escape_next = False
    for ch in s:
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == '\\' and in_string:
            result.append(ch)
            escape_next = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        else:
            result.append(ch)
    return ''.join(result)


def _extract_fields_regex(s: str) -> dict | None:
    """
    Last-resort regex extraction for flat LLM JSON objects.
    Handles unescaped quotes inside string values by stopping at the next
    unescaped quote, yielding at least partial (useful) field values.
    """
    result = {}
    for m in re.finditer(r'"(\w+)"\s*:\s*"((?:[^"\\]|\\.)*)"', s, re.DOTALL):
        result[m.group(1)] = m.group(2)
    return result if result else None


def parse_json(raw: str):
    """
    Robustly extract a JSON object or array from an LLM response.
    Strips markdown fences, finds the first { or [ and parses from there.
    Falls back through three sanitization tiers before giving up.
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

    # Tier 1: standard parse
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    # Tier 2: fix literal control chars + invalid escape sequences
    try:
        sanitized = _fix_invalid_escapes(_fix_literal_control_chars(clean))
        return json.loads(sanitized)
    except json.JSONDecodeError:
        pass

    # Tier 3: regex field extraction (handles unescaped quotes in values)
    extracted = _extract_fields_regex(clean)
    if extracted:
        return extracted

    raise ValueError(f"All JSON parse strategies failed for response:\n{raw[:300]}")


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
