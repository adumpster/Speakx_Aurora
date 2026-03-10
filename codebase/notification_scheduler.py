"""
Project Aurora — Master Segment Scheduler (Clean Output)
======================================================================
1. Generates a clean Segment-Level master curriculum.
2. ALIGNMENT: Dynamically maps template IDs to their exact Phase Name under the hood.
3. OUTPUT: Strictly saves to `iteration_0_before_learning/user_notification_schedule.csv`.
4. REMOVED: `phase_name` and `primary_goal` columns from the final CSV for a cleaner look.
"""

import pandas as pd
import numpy as np
import os
import re
import logging

from config import OUTPUT_DIR_0

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("aurora.scheduler")

# ──────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────
INPUT_SEGMENTS  = "user_segments.csv"
INPUT_TIMING    = "timing_recommendations.csv"
INPUT_TEMPLATES = "message_templates.csv" 
INPUT_GOALS     = "segment_goals.csv"

OUTPUT_DIR      = OUTPUT_DIR_0
OUTPUT_FILE     = "user_notification_schedule.csv" 

ALL_WINDOWS = ['early_morning', 'mid_morning', 'afternoon', 'late_afternoon', 'evening', 'night']

def resolve_file(filepath):
    """Smart file hunter to find CSVs even if they are in subfolders or renamed"""
    if os.path.exists(filepath): return filepath
    if os.path.exists(os.path.join(OUTPUT_DIR, filepath)): 
        return os.path.join(OUTPUT_DIR, filepath)
        
    base_name = os.path.basename(filepath).split('.')[0]
    base_clean = re.sub(r'\s*\(\d+\)', '', base_name)
    for file in os.listdir('.'):
        if file.startswith(base_clean) and file.endswith('.csv'): return file
    return filepath

def run_pipeline():
    logger.info("Loading datasets for Segment-Wise Matrix...")
    try:
        segments_df   = pd.read_csv(resolve_file(INPUT_SEGMENTS))
        timing_df     = pd.read_csv(resolve_file(INPUT_TIMING))
        templates_df  = pd.read_csv(resolve_file(INPUT_TEMPLATES))
        goals_df      = pd.read_csv(resolve_file(INPUT_GOALS))
    except FileNotFoundError as e:
        logger.error("Missing required file: %s", e)
        return

    # Clean whitespace from column headers
    for df in [segments_df, timing_df, templates_df, goals_df]:
        df.columns = df.columns.str.strip()

    logger.info("Pillar 1: Data Sanitization & Segment Matching...")
    def clean_seg(series):
        return series.astype(str).str.extract(r'(\d+)')[0].fillna(0).astype(int)

    segments_df['clean_seg_id']  = clean_seg(segments_df['segment_id'])
    timing_df['clean_seg_id']    = clean_seg(timing_df['segment_id'])
    
    # Safely extract template ID column
    temp_col = 'template_id' if 'template_id' in templates_df.columns else templates_df.columns[0]
    templates_df['clean_seg_id'] = clean_seg(templates_df[temp_col])
    goals_df['clean_seg_id']     = clean_seg(goals_df['segment_id'])

    # Calculate Limits [8, 5, 2] based on Segment Average Activeness
    seg_agg = segments_df.groupby(['clean_seg_id', 'segment_name', 'lifecycle_stage']).agg({'activeness_score': 'mean'}).reset_index()
    seg_agg['activeness_score'] = seg_agg['activeness_score'].fillna(0.5)
    
    conditions = [
        seg_agg['activeness_score'] >= 0.7,
        seg_agg['activeness_score'] >= 0.4,
        seg_agg['activeness_score'] < 0.4
    ]
    seg_agg['final_frequency'] = np.select(conditions, [8, 5, 3], default=3)
    
    freq_dict = seg_agg.set_index('clean_seg_id')['final_frequency'].to_dict()
    name_dict = seg_agg.set_index('clean_seg_id')['segment_name'].to_dict()
    stage_dict = seg_agg.set_index('clean_seg_id')['lifecycle_stage'].to_dict()
    activeness_dict = seg_agg.set_index('clean_seg_id')['activeness_score'].to_dict()

    timing_dict = timing_df.groupby('clean_seg_id')['recommended_time_window'].apply(list).to_dict()

    logger.info("Pillar 2: Internal Daywise Template Alignment Engine...")
    
    # Clean Phase Names for bulletproof matching
    unique_phases = goals_df['phase_name'].dropna().unique()
    def normalize_text(text): return re.sub(r'[^A-Z0-9]', '', str(text).upper())
    phase_map = {normalize_text(p): p for p in unique_phases}
    
    def extract_phase_from_id(tid):
        tid_norm = normalize_text(tid)
        for norm_p, orig_p in sorted(phase_map.items(), key=lambda x: len(x[0]), reverse=True):
            if norm_p in tid_norm:
                return orig_p
        return "General"
        
    templates_df['phase_name'] = templates_df[temp_col].apply(extract_phase_from_id)

    # Group templates by BOTH Segment AND Phase Name!
    template_dict = templates_df.groupby(['clean_seg_id', 'phase_name'])[temp_col].apply(list).to_dict()
    fallback_templates = templates_df.groupby('clean_seg_id')[temp_col].apply(list).to_dict()

    logger.info("Pillar 3: Unpacking the Segment Curriculum Grid...")
    expanded_goals = []
    for _, row in goals_df.iterrows():
        dr = str(row.get('day_range', '')).lower()
        nums = [int(x) for x in re.findall(r'\d+', dr)]
        
        days_to_map = []
        if 'x+' in dr or '31+' in dr or 'inactive' in str(row.get('lifecycle_stage','')).lower() or 'churned' in str(row.get('lifecycle_stage','')).lower():
            days_to_map = [31, 37, 44, 51, 58, 65]
        elif len(nums) == 2:
            days_to_map = list(range(nums[0], nums[1] + 1))  
        elif len(nums) == 1:
            days_to_map = [nums[0]]
            
        for d in days_to_map:
            expanded_goals.append({
                "clean_seg_id": row["clean_seg_id"],
                "segment_id": row["segment_id"],
                "lifecycle_stage": row.get("lifecycle_stage", stage_dict.get(row["clean_seg_id"], "unknown")),
                "day_num": d,
                "phase_name": row.get("phase_name", "General") # Used internally
            })
            
    master_grid = pd.DataFrame(expanded_goals).sort_values(by=['clean_seg_id', 'day_num'])

    logger.info("Pillar 4: Populating the Master Roadmap...")
    schedule_records = []

    for row in master_grid.itertuples(index=False):
        freq = int(freq_dict.get(row.clean_seg_id, 3))
        
        # 🌟 FETCH ALIGNED TEMPLATES ONLY (Logic stays, output goes)
        user_templates = template_dict.get((row.clean_seg_id, row.phase_name))
        if not user_templates: 
            user_templates = fallback_templates.get(row.clean_seg_id, ['T_DEFAULT_01'])
            
        pref_times = timing_dict.get(row.clean_seg_id, ['evening'])
        pref_times = list(dict.fromkeys(pref_times)) 
        
        other_times = [w for w in ALL_WINDOWS if w not in pref_times]
        if not other_times: other_times = ALL_WINDOWS 
        
            
        pref_count = max(1, int(freq * 0.75)) 
        
        # Removed phase_name and primary_goal from the dictionary
        row_dict = {
            'segment_id': row.segment_id,
            'segment_name': name_dict.get(row.clean_seg_id, f"Segment {row.clean_seg_id}"),
            'lifecycle_stage': row.lifecycle_stage,
            'lifecycle_day': f"D{row.day_num}"
        }
        
        score = activeness_dict.get(row.clean_seg_id, 0.5)
        
        if score >= 0.7:
            push_count = max(1, int(round(freq * 0.5)))
            inapp_count = freq - push_count
            channels_list = ["push_notification"] * push_count + ["in_app_message"] * inapp_count
        elif score >= 0.4:
            push_count = max(1, int(round(freq * 0.75)))
            inapp_count = freq - push_count
            channels_list = ["push_notification"] * push_count + ["in_app_message"] * inapp_count
        else:
            email_count = max(1, int(round(freq * 0.5)))
            push_count = freq - email_count
            channels_list = ["email"] * email_count + ["push_notification"] * push_count
            
        for slot in range(1, 10):
            if slot <= freq and len(user_templates) > 0:
                if slot <= pref_count: active_times = pref_times
                else: active_times = other_times
                    
                w_idx = (slot + row.day_num) % len(active_times)
                t_idx = (slot + row.day_num) % len(user_templates)
                c_idx = (slot - 1) % len(channels_list)
                
                time_window = active_times[w_idx]
                template = user_templates[t_idx]
                channel = channels_list[c_idx]
                
                row_dict[f'notif_{slot}'] = f"({template}, {time_window}, {channel})"
            else:
                row_dict[f'notif_{slot}'] = ""
                
        schedule_records.append(row_dict)

    logger.info("Exporting Clean Timeline...")
    schedule_df = pd.DataFrame(schedule_records)
    
    # 🌟 DEFINING CLEAN COLUMNS: Only Core Info + Notification Slots 🌟
    cols = ['segment_id', 'segment_name', 'lifecycle_stage', 'lifecycle_day'] + [f'notif_{i}' for i in range(1, 10)]
    schedule_df = schedule_df[cols]
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    schedule_df.to_csv(out_path, index=False)
    
    logger.info("=" * 60)
    logger.info("📅 SUCCESS: CLEAN CSV GENERATED")
    logger.info(f"  Removed:          phase_name, primary_goal")
    logger.info(f"  Under the hood:   Templates are still perfectly phase-aligned!")
    logger.info(f"  Saved to:         {out_path}")
    logger.info("=" * 60)

if __name__ == "__main__":
    run_pipeline()
