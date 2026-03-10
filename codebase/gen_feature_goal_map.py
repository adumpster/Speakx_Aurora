# gen_feature_goal_map.py  →  feature_goal_map.json
# Domain-agnostic: discovers features from feature_* CSV columns.
# Change from original: kb.retrieve() replaced with load_kb() injection.

import json
import pandas as pd

from kb_loader   import load_kb
from llm         import llm, parse_json, save_json
from data_loader import DataProfile


def _extract_features(df: pd.DataFrame, feature_cols: list) -> list:
    features = []
    for col in feature_cols:
        name       = col[len("feature_"):]
        mask       = df[col].astype(bool)
        stages     = sorted(df.loc[mask, "lifecycle_stage"].dropna().unique().tolist())
        usage_rate = round(float(mask.mean()), 3)
        features.append({"column": col, "name": name,
                          "lifecycle_stages": stages, "usage_rate": usage_rate})
        print(f"  [data] {col}: used in {stages} (rate={usage_rate:.1%})")
    return features


def _gen_feature_entry(kb: str, profile: DataProfile,
                       feature: dict, fid: str, ns: dict) -> dict:
    raw = llm(
        system="You are a product growth strategist. Output ONLY valid JSON.",
        prompt=f"""KNOWLEDGE BASE:\n{kb}\n\nDATASET SUMMARY:\n{profile.summary}

Feature         : {feature['name']}
Usage rate      : {feature['usage_rate']:.1%}
Lifecycle stages where actually used: {feature['lifecycle_stages']}
North Star      : {ns['metric_name']} — {ns['definition']}

Return ONLY valid JSON:
{{
  "feature":                 "<human-readable name>",
  "feature_id":              "{fid}",
  "description":             "<one-line description>",
  "lifecycle_stage":         {json.dumps(feature['lifecycle_stages'])},
  "primary_goal":            "<main goal this feature drives>",
  "sub_goals":               ["<goal 1>", "<goal 2>"],
  "north_star_contribution": "<how it moves {ns['metric_name']}>",
  "propensity_levers":       ["<lever 1>", "<lever 2>"],
  "expected_outcome":        "<measurable outcome>"
}}"""
    )
    try:
        entry = parse_json(raw)
        if isinstance(entry, list):
            entry = entry[0]
    except Exception as e:
        print(f"  [warn] parse failed for '{feature['name']}': {e}")
        entry = {}

    if not isinstance(entry, dict) or not entry:
        entry = {
            "feature": feature["name"].replace("_", " ").title(),
            "feature_id": fid,
            "description": f"Feature: {feature['name']}",
            "primary_goal": "Increase engagement",
            "sub_goals": ["Improve session frequency", "Build habit"],
            "north_star_contribution": "Indirect via engagement",
            "propensity_levers": ["usage_rate", "lifecycle_stage"],
            "expected_outcome": "Higher retention rate",
        }

    entry["lifecycle_stage"] = feature["lifecycle_stages"]
    return entry


def gen_feature_goal_map(profile: DataProfile, north_star: dict, output_dir: str = None) -> dict:
    print("\n[2/6] Generating feature_goal_map.json ...")
    kb = load_kb()
    ns = north_star["inferred_north_star"]

    features = _extract_features(profile.df, profile.feature_cols)
    print(f"  Found {len(features)} feature(s): {[f['name'] for f in features]}")

    entries = []
    for i, feat in enumerate(features):
        fid = f"feat_{i+1:03d}"
        print(f"  [{i+1}/{len(features)}] {feat['name']} ...")
        entries.append(_gen_feature_entry(kb, profile, feat, fid, ns))

    data = {"feature_goal_map": entries, "generated_at": "2026-03-07", "iteration": 0}
    save_json(data, "feature_goal_map.json", output_dir)
    return data