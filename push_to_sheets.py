"""
Push existing scraped data (from output/ folder) to Google Sheets
without re-scraping Strava. Useful when you've already scraped
but the Sheets upload failed, or you're rate-limited by Strava.

Usage:
    python push_to_sheets.py
"""

import os
import pandas as pd

from src.google_sheets import get_sheets_service, write_google_sheet, update_execution_time
from src.sheets_formatter import prepare_weekly_data_from_activities, write_sports_challenge_sheet
from main import load_config

# Load config
config = load_config()

sheet_id = config.get('GOOGLE_DOCS', 'SHEET_ID')
date_min = config.get('GENERAL', 'DATE_MIN')
timezone = config.get('GENERAL', 'TIMEZONE', fallback='Asia/Singapore')
google_api_key = os.path.join(os.path.dirname(__file__), 'settings', 'keys.json')

scoring_config = {
    'swim_km_per_point': config.getfloat('SCORING', 'SWIM_KM_PER_POINT', fallback=2.0),
    'run_km_per_point': config.getfloat('SCORING', 'RUN_KM_PER_POINT', fallback=10.0),
    'bike_km_per_point': config.getfloat('SCORING', 'BIKE_KM_PER_POINT', fallback=40.0),
}

# Load existing data from output/
output_dir = 'output'

members_df = pd.read_csv(os.path.join(output_dir, 'members.csv'), dtype=str)
activities_df = pd.read_csv(os.path.join(output_dir, 'activities.csv'), dtype=str)

print(f"Loaded {len(members_df)} members, {len(activities_df)} activities from output/")
print(f"Pushing to Google Sheet: {sheet_id}")
print(f"Week 3 starts: {date_min}")

# Connect to Google Sheets
service = get_sheets_service(google_api_key)

# Build weekly data and write to 'Sports Challenge' tab
weekly_data = prepare_weekly_data_from_activities(
    activities_df=activities_df,
    members_df=members_df,
    scoring_config=scoring_config,
    week_start_date=date_min,
)

write_sports_challenge_sheet(
    service=service,
    sheet_id=sheet_id,
    sheet_name='Sports Challenge',
    weekly_data=weekly_data,
)
print("✓ Updated 'Sports Challenge' sheet")

# Update Members tab
write_google_sheet(service=service, sheet_id=sheet_id, sheet_name='Members', df=members_df)
print("✓ Updated 'Members' sheet")

# Update execution time
update_execution_time(service=service, sheet_id=sheet_id, sheet_name='Execution Time', timezone=timezone)
print("✓ Done!")
