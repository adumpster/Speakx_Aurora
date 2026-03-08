import pandas as pd
import os
from datetime import datetime, timedelta

def generate_notification_schedule():
    print("Initializing Deterministic Scheduling Engine...")

    # 1. Define File Paths
    # Assuming your files are in the main directory or 'iteration 0 before learning'
    users_file = "user_segments.csv"
    goals_file = "segment_goals.csv"
    templates_file = "message_templates.csv"

    # 2. Load the Core Data
    if not os.path.exists(users_file) or not os.path.exists(goals_file):
        print("ERROR: Missing user_segments.csv or segment_goals.csv!")
        return
        
    df_users = pd.read_csv(users_file)
    df_goals = pd.read_csv(goals_file)
    
    # 3. Handle Templates (With Fail-Safe if LLM is still generating)
    if os.path.exists(templates_file):
        df_templates = pd.read_csv(templates_file)
        # Ensure column name consistency (some scripts use 'goal', some 'primary_goal')
        if 'goal' in df_templates.columns:
            df_templates = df_templates.rename(columns={'goal': 'primary_goal'})
    else:
        print("Notice: message_templates.csv not found. Using placeholder template IDs to ensure pipeline completion.")
        df_templates = pd.DataFrame(columns=['segment_id', 'lifecycle_stage', 'primary_goal', 'template_id'])

    # 4. STEP 1: Join Users to their Segment Goals (The "What" and "When in Lifecycle")
    print("Mapping users to their daily lifecycle goals...")
    # This creates a row for every single day of a user's lifecycle journey
    schedule_df = pd.merge(df_users, df_goals, on=['segment_id', 'lifecycle_stage'], how='inner')

    # 5. STEP 2: Join the exact Message Template (The "Exact Text")
    print("Assigning AI-generated templates...")
    if not df_templates.empty:
        # We drop duplicates just in case the LLM generated multiple templates per goal, 
        # picking the first one to ensure 1 notification per user per day.
        df_templates_unique = df_templates.drop_duplicates(subset=['segment_id', 'lifecycle_stage', 'primary_goal'])
        schedule_df = pd.merge(schedule_df, df_templates_unique[['segment_id', 'lifecycle_stage', 'primary_goal', 'template_id']], 
                               on=['segment_id', 'lifecycle_stage', 'primary_goal'], 
                               how='left')
    else:
        schedule_df['template_id'] = None

    # Fill any missing templates with a placeholder so the system doesn't break
    schedule_df['template_id'] = schedule_df['template_id'].fillna("TPL_DEFAULT_01")

    # 6. STEP 3: Calculate the Exact Send Timestamp
    print("Calculating precise delivery timestamps based on preferred hours...")
    
    base_date = datetime.strptime("2026-03-09", "%Y-%m-%d") # Starting date for the schedule
    
    def calculate_timestamp(row):
        # Extract the integer from the Day string (e.g., "D1" -> 1, "D8" -> 8)
        try:
            day_offset = int(str(row['day']).replace('D', '').strip())
        except:
            day_offset = 0 # Default to Day 0 if formatting is weird
            
        # Get user's preferred hour, default to 18 (6 PM) if missing
        preferred_hour = int(row.get('preferred_hour', 18))
        
        # Calculate final datetime: Base Date + Lifecycle Day Offset + Preferred Hour
        send_time = base_date + timedelta(days=day_offset, hours=preferred_hour)
        return send_time.strftime("%Y-%m-%d %H:%00:%00")

    schedule_df['send_timestamp'] = schedule_df.apply(calculate_timestamp, axis=1)

    # 7. STEP 4: Format Final Output for the Backend Engineering Team
    final_output = schedule_df[[
        'user_id', 
        'segment_id',
        'lifecycle_stage',
        'day',
        'primary_goal',
        'template_id', 
        'send_timestamp'
    ]].sort_values(by=['user_id', 'send_timestamp'])

    # 8. Save the Deliverable
    output_path = "user_notification_schedule.csv"
    final_output.to_csv(output_path, index=False)
    
    print(f"\n✅ SUCCESS! Generated {len(final_output)} scheduled notifications.")
    print(f"File saved to: {output_path}")
    print("\nPreview of the Engine Output:")
    print(final_output[['user_id', 'template_id', 'send_timestamp', 'day']].head(5).to_string(index=False))

if __name__ == "__main__":
    generate_notification_schedule()