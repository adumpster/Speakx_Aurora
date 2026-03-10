# kb_loader.py
# ─────────────────────────────────────────────────────────────
# Loads the company Knowledge Bank (a plain .txt or .md file)
# and makes it available for direct injection into LLM prompts.
#
# WHY NO RAG:
#   The KB is intentionally small (1-2 pages / ~2000-4000 chars).
#   For a document this size, full injection is strictly better
#   than RAG — nothing gets missed by a retrieval step, and you
#   don't need ChromaDB, embeddings, or any vector infrastructure.
#
# DOMAIN AGNOSTICITY:
#   Swap speakx_kb.txt for any other company's KB markdown and
#   the entire pipeline re-purposes itself automatically.
#   Every generator calls build_context() which returns:
#     [KB full text] + [behavioral data summary]
#   so the LLM always reasons from both company knowledge AND
#   real user numbers simultaneously.
# ─────────────────────────────────────────────────────────────

import os
from config import KB_PATH


# ── Module-level cache so the file is only read once ─────────
_kb_cache: str | None = None


def load_kb(path: str = KB_PATH) -> str:
    """
    Read the KB file and return its full text.
    Caches the result so repeated calls are free.

    Returns empty string (with a warning) if the file doesn't
    exist — the system degrades gracefully and relies on
    behavioral data alone.
    """
    global _kb_cache
    if _kb_cache is not None:
        return _kb_cache

    if not os.path.exists(path):
        print(f"  [kb] WARNING: KB file not found at '{path}'")
        print(f"  [kb] Generators will use behavioral data context only.")
        _kb_cache = ""
        return _kb_cache

    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()

    _kb_cache = raw
    print(f"  [kb] Loaded KB: {len(_kb_cache)} chars from '{path}'")
    return _kb_cache


def get_kb_section(heading: str, path: str = KB_PATH) -> str:
    """
    Extract a specific section from the KB by heading name.
    Useful when you want to inject only the relevant section
    into a prompt (e.g. just 'Ethical Communication Guidelines'
    for the tone matrix generator).

    Returns the full KB text if the heading is not found.
    """
    kb = load_kb(path)
    if not kb:
        return ""

    lines = kb.splitlines()
    section_lines = []
    in_section = False

    for line in lines:
        # Match markdown headings (# or ##) containing the search text
        if line.startswith("#") and heading.lower() in line.lower():
            in_section = True
            section_lines.append(line)
            continue

        if in_section:
            # Stop at the next same-or-higher level heading
            if line.startswith("#") and heading.lower() not in line.lower():
                break
            section_lines.append(line)

    if section_lines:
        return "\n".join(section_lines).strip()

    # Heading not found — return full KB so nothing is lost
    return kb


def build_context(data_summary: str, path: str = KB_PATH) -> str:
    """
    The main function every generator calls.

    Returns a single string combining:
      1. The full KB text  — company vision, north star, features,
                             tones, personas, metrics, journey stages
      2. The behavioral data summary — real numbers from the CSV:
                             stage distribution, feature usage %,
                             per-stage averages, propensity signals

    Having both in the same prompt means the LLM can:
      - Extract the north star metric AS stated in the KB
      - Cross-check it against what users actually do in the data
      - Ground feature descriptions in real usage numbers
      - Respect the ethical tone guidelines from the KB
      - Personalise goals using actual behavioral averages
    """
    kb = load_kb(path)

    sections = []

    if kb:
        sections.append("=" * 60)
        sections.append("COMPANY KNOWLEDGE BANK")
        sections.append("=" * 60)
        sections.append(kb)
        sections.append("")

    sections.append("=" * 60)
    sections.append("BEHAVIORAL DATA SUMMARY  (computed from user CSV)")
    sections.append("=" * 60)
    sections.append(data_summary)

    return "\n".join(sections)
