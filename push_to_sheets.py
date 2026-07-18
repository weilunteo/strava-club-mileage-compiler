"""
Push existing scraped data (from output/) to Google Sheets without re-scraping.
Useful when Strava is rate-limiting you.

Usage:
    python push_to_sheets.py
"""

import os
import pandas as pd

from src.google_sheets import get_sheets_service, write_google_sheet, update_execution_time
from src.sheets_formatter import (
    prepare_weekly_data_from_activities,
    write_sports_challenge_sheet,
    build_individual_leaderboard,
)
from main import load_config

config = load_config()

sheet_id = config.get('GOOGLE_DOCS', 'SHEET_ID')
date_min = config.get('GENERAL', 'DATE_MIN')
timezone = config.get('GENERAL', 'TIMEZONE', fallback='Asia/Singapore')
google_api_key = os.path.join(os.path.dirname(__file__), 'settings', 'keys.json')

output_dir = 'output'

members_df = pd.read_csv(os.path.join(output_dir, 'members.csv'), dtype=str)
activities_df = pd.read_csv(os.path.join(output_dir, 'activities.csv'), dtype=str)

print(f"Loaded {len(members_df)} members, {len(activities_df)} activities from {output_dir}/")
print(f"Pushing to Google Sheet: {sheet_id}")
print(f"Week 3 starts: {date_min}")

service = get_sheets_service(google_api_key)

weekly_data = prepare_weekly_data_from_activities(
    activities_df=activities_df,
    members_df=members_df,
    week_start_date=date_min,
)

write_sports_challenge_sheet(
    service=service,
    sheet_id=sheet_id,
    sheet_name='Sports Challenge',
    weekly_data=weekly_data,
)
print("✓ Updated 'Sports Challenge' sheet")

# Individual leaderboard
individual_lb = build_individual_leaderboard(
    activities_df=activities_df,
    members_df=members_df,
    week_start_date=date_min,
)
if not individual_lb.empty:
    write_google_sheet(
        service=service,
        sheet_id=sheet_id,
        sheet_name='Individual Leaderboard',
        df=individual_lb,
    )
    print(f"✓ Updated 'Individual Leaderboard' sheet ({len(individual_lb)} athletes)")

write_google_sheet(service=service, sheet_id=sheet_id, sheet_name='Members', df=members_df)
print("✓ Updated 'Members' sheet")

update_execution_time(service=service, sheet_id=sheet_id, sheet_name='Execution Time', timezone=timezone)
print("✓ Done!")
