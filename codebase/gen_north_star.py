# gen_north_star.py  →  company_north_star.json
# 3-layer approach: L1 explicit KB, L2 scored inference, L3 full JSON build.

from kb_loader   import load_kb
from llm         import llm, parse_json, safe_parse_json, save_json
from data_loader import DataProfile


def _unwrap(raw_parsed):
    """If LLM returns a list instead of a dict, grab the first element."""
    if isinstance(raw_parsed, list):
        return raw_parsed[0] if raw_parsed else {}
    if isinstance(raw_parsed, dict):
        return raw_parsed
    return {}


def gen_north_star(profile: DataProfile, output_dir: str = None) -> dict:
    print("\n[1/6] Generating company_north_star.json ...")
    kb = load_kb()

    # Layer 1: explicit extraction
    print("  [L1] Checking if North Star is explicitly stated in KB ...")
    raw_l1 = llm(
        system="You are a data extraction engine. Output ONLY valid JSON, no explanation.",
        prompt=f"""KNOWLEDGE BASE:\n{kb}\n\nDATASET SUMMARY:\n{profile.summary}

Look at the KNOWLEDGE BASE above. Is there any section heading, label, or bold
text that designates a specific metric as the company's north star, primary
metric, most important metric, or key metric?

Examples of what to look for:
- A section called "North Star Metric" followed by a metric name
- A label like "Primary North Star: <metric>" or "Key Metric: <metric>"
- Any statement like "our north star is <metric>"

If such a designation exists, set "explicitly_stated" to true and extract the
metric name and the exact line/sentence from the KB.

Return ONLY a single JSON object (not an array):
{{
  "explicitly_stated": true,
  "metric_name": "<exact metric name if found, else null>",
  "exact_quote": "<the exact line from the KB that designates it, else null>"
}}"""
    )
    extracted = _unwrap(safe_parse_json(raw_l1, fallback={"explicitly_stated": False}))
    method = "explicit_extraction"

    # Layer 2: scored inference fallback
    if not extracted.get("explicitly_stated"):
        print("  [L2] Not explicit — running structured scoring ...")
        raw_l2 = llm(
            system="You are a product analytics expert. Output ONLY valid JSON.",
            prompt=f"""KNOWLEDGE BASE:\n{kb}\n\nDATASET SUMMARY:\n{profile.summary}

Score each candidate metric 0-10 on three criteria:
  1. revenue_correlation  2. user_value_signal  3. actionability

Candidates: Monthly Retention, W1 Retention, DAU/MAU,
  Trial-to-Paid Conversion, Notification CTR, Session Count

Return ONLY a single JSON object (not an array):
{{
  "scores": [{{"metric": "<n>", "revenue_correlation": 7, "user_value_signal": 8, "actionability": 9, "total": 24}}],
  "winner": "<metric with highest total>",
  "reasoning": "<2-3 sentences>"
}}"""
        )
        scored    = _unwrap(safe_parse_json(raw_l2, fallback={"winner": "W1 Retention", "reasoning": "High revenue correlation."}))
        extracted = scored
        method    = "scored_inference"
        print(f"  [L2] Winner: {scored.get('winner')} — {str(scored.get('reasoning',''))[:80]}...")

    metric_name = extracted.get("metric_name") or extracted.get("winner") or "W1 Retention"
    reasoning   = extracted.get("exact_quote")  or extracted.get("reasoning", "")

    # Layer 3: full structured JSON
    print(f"  [L3] Building JSON for: {metric_name}")
    raw_l3 = llm(
        system="You are a product analytics expert. Output ONLY valid JSON, no markdown.",
        prompt=f"""KNOWLEDGE BASE:\n{kb}\n\nDATASET SUMMARY:\n{profile.summary}

North Star Metric: {metric_name}
Determination method: {method}
Supporting reasoning: {reasoning}

Return ONLY a single JSON object (not an array):
{{
  "company": "<company name from KB, or Unknown>",
  "inferred_north_star": {{
    "metric_name": "{metric_name}",
    "how_it_was_determined": "{method}",
    "definition": "<clear 1-2 sentence definition>",
    "justification": "<why this is the north star — 2-3 sentences>",
    "measurable_proxy": "<formula using CSV columns>"
  }},
  "supporting_metrics": [
    {{"name": "<metric>", "definition": "<def>", "why_it_matters": "<1-2 sentences>"}}
  ],
  "lifecycle_stages": [
    {{"stage": "trial",    "day_range": "D0-D7",  "primary_goal": "<goal>"}},
    {{"stage": "paid",     "day_range": "D8-D30", "primary_goal": "<goal>"}},
    {{"stage": "churned",  "day_range": "D31+",   "primary_goal": "<goal>"}},
    {{"stage": "inactive", "day_range": "D31+",   "primary_goal": "<goal>"}}
  ],
  "generated_at": "2026-03-07",
  "iteration": 0
}}"""
    )

    data = _unwrap(safe_parse_json(raw_l3, fallback={
        "company": "SpeakX",
        "inferred_north_star": {
            "metric_name": metric_name,
            "how_it_was_determined": method,
            "definition": "Users completing at least one exercise in week 1 after trial conversion.",
            "justification": reasoning,
            "measurable_proxy": "exercises_completed_7d >= 1 within 7 days of paid conversion"
        },
        "supporting_metrics": [],
        "lifecycle_stages": [],
        "generated_at": "2026-03-07",
        "iteration": 0
    }))

    save_json(data, "company_north_star.json", output_dir)
    return data