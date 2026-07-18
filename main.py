"""
Strava Club Mileage Compiler - Main Entry Point

Scrapes Strava club data and updates the 'Sports Challenge' Google Sheet
with weekly mileage & points per division (FMD, IND, EDR, BEK, VIC).

Point system (per km):
    Run  (pace < 9 min/km):  0.10 pt/km  (10 km = 1 pt)
    Walk (pace >= 9 min/km): 0.05 pt/km  (20 km = 1 pt)
    Swim:                    0.50 pt/km  (2 km = 1 pt)
    Bike:                    0.025 pt/km (40 km = 1 pt)

Usage:
    python main.py                    # Full run (scrape + push to sheets)
    python main.py --no-sheets        # Scrape only, save CSVs locally
    python main.py --leaderboard-only # Skip individual activities
"""

import argparse
import configparser
import os

import pandas as pd

from src.strava_scraper import (
    strava_authentication,
    strava_club_activities,
    strava_club_leaderboard,
    strava_club_members,
    quit_driver,
)
from src.google_sheets import (
    get_sheets_service,
    write_google_sheet,
    update_google_sheet_incremental,
    update_execution_time,
)
from src.sheets_formatter import (
    prepare_weekly_data_from_activities,
    write_sports_challenge_sheet,
    build_individual_leaderboard,
)


def load_config(config_path: str = None) -> configparser.ConfigParser:
    """Load configuration from config.ini."""
    config = configparser.ConfigParser()
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), 'settings', 'config.ini')
    if os.path.exists(config_path):
        config.read(config_path, encoding='utf-8')
    return config


def get_division_teams(config: configparser.ConfigParser) -> dict[str, list[str]] | None:
    """Parse CLUB_MEMBERS_TEAMS from config into a dictionary."""
    try:
        teams_str = config.get('STRAVA', 'CLUB_MEMBERS_TEAMS')
    except (KeyError, configparser.NoSectionError, configparser.NoOptionError):
        return None
    if not teams_str:
        return None

    teams = {}
    for entry in teams_str.split(';'):
        entry = entry.strip()
        if ':' not in entry:
            continue
        name, ids = entry.split(':', 1)
        teams[name.strip()] = [aid.strip() for aid in ids.split(',')]
    return teams


def main():
    ap = argparse.ArgumentParser(description='Strava Club Mileage Compiler')
    ap.add_argument('--config', type=str, help='Path to config.ini')
    ap.add_argument('--headless', action='store_true', help='Run browser in headless mode')
    ap.add_argument('--leaderboard-only', action='store_true', help='Skip individual activities')
    ap.add_argument('--no-sheets', action='store_true', help='Skip Google Sheets update')
    ap.add_argument('--output-dir', type=str, default='output', help='Output directory')
    args = ap.parse_args()

    config = load_config(args.config)

    # Settings
    date_min = config.get('GENERAL', 'DATE_MIN', fallback='2026-07-13')
    date_max = config.get('GENERAL', 'DATE_MAX', fallback='2026-12-06')
    timezone = config.get('GENERAL', 'TIMEZONE', fallback='Asia/Singapore')
    club_ids = config.get('STRAVA', 'CLUB_IDS', fallback='2231427').split(', ')
    strava_login = config.get('STRAVA', 'LOGIN', fallback='')
    strava_password = config.get('STRAVA', 'PASSWORD', fallback='')
    scrap_activities = config.getboolean('GENERAL', 'SCRAP_CLUB_ACTIVITIES', fallback=True)
    sheet_id = config.get('GOOGLE_DOCS', 'SHEET_ID', fallback='')

    google_api_key = os.path.join(os.path.dirname(__file__), 'settings', 'keys.json')
    if not os.path.exists(google_api_key):
        google_api_key = None

    division_teams = get_division_teams(config)
    os.makedirs(args.output_dir, exist_ok=True)

    print("=" * 60)
    print("STRAVA CLUB MILEAGE COMPILER")
    print("=" * 60)
    print(f"Club IDs: {club_ids}")
    print(f"Date range: {date_min} to {date_max}")
    print(f"Divisions configured: {list(division_teams.keys()) if division_teams else 'None'}")
    print("Points: Run 0.1/km | Walk 0.05/km | Swim 0.5/km | Bike 0.025/km")
    print("=" * 60)

    # --- Step 1: Auth ---
    print("\n[1/5] Authenticating to Strava...")
    login_mode = 'credentials' if strava_login and strava_password and strava_login != 'your_email@example.com' else 'user'
    strava_authentication(
        strava_login=strava_login,
        strava_password=strava_password,
        headless=args.headless,
        login_mode=login_mode,
    )

    # --- Step 2: Members ---
    print("\n[2/5] Scraping club members...")
    members_df = strava_club_members(
        club_ids=club_ids,
        club_members_teams=division_teams,
        timezone=timezone,
    )
    print(f"  Found {len(members_df)} members")

    # Apply division assignments from config
    if division_teams:
        id_to_div = {}
        for div, ids in division_teams.items():
            for aid in ids:
                # Handle multi-division assignments (comma-joined)
                if aid in id_to_div:
                    id_to_div[aid] = f"{id_to_div[aid]}, {div}"
                else:
                    id_to_div[aid] = div
        members_df['athlete_team'] = members_df['athlete_id'].map(id_to_div)

        for div in ['FMD', 'IND', 'EDR', 'BEK', 'VIC']:
            count = len(division_teams.get(div, []))
            print(f"    {div}: {count} members")
    else:
        print("  ⚠ No division assignments in config. Run setup_divisions.py first.")

    members_df.to_csv(os.path.join(args.output_dir, 'members.csv'), index=False)

    # --- Step 3: Leaderboard ---
    print("\n[3/5] Scraping club leaderboard...")
    leaderboard_df = strava_club_leaderboard(
        club_ids=club_ids,
        filter_date_min=date_min,
        filter_date_max=date_max,
        timezone=timezone,
    )
    print(f"  Scraped {len(leaderboard_df)} leaderboard entries")
    leaderboard_df.to_csv(os.path.join(args.output_dir, 'leaderboard.csv'), index=False)

    # --- Step 4: Activities (with history merge) ---
    activities_df = pd.DataFrame()
    activities_path = os.path.join(args.output_dir, 'activities.csv')

    if scrap_activities and not args.leaderboard_only:
        print("\n[4/5] Scraping individual activities...")
        new_df = strava_club_activities(
            club_ids=club_ids,
            filter_activities_type=None,
            filter_date_min=date_min,
            filter_date_max=date_max,
            timezone=timezone,
        )
        print(f"  Scraped {len(new_df)} new activities")

        if os.path.exists(activities_path):
            existing = pd.read_csv(activities_path, dtype=str)
            activities_df = pd.concat([existing, new_df], ignore_index=True)
            activities_df = activities_df.drop_duplicates(subset=['activity_id'], keep='last', ignore_index=True)
            print(f"  Merged with history: {len(activities_df)} total activities")
        else:
            activities_df = new_df

        if not activities_df.empty:
            activities_df.to_csv(activities_path, index=False)
    else:
        print("\n[4/5] Skipping activity scrape")
        if os.path.exists(activities_path):
            activities_df = pd.read_csv(activities_path, dtype=str)
            print(f"  Loaded {len(activities_df)} activities from history")

    # --- Step 5: Calculate weekly data ---
    print("\n[5/5] Calculating weekly scores...")
    weekly_data = {}
    if not activities_df.empty and division_teams:
        weekly_data = prepare_weekly_data_from_activities(
            activities_df=activities_df,
            members_df=members_df,
            week_start_date=date_min,
        )

        # Print summary
        print("\n  Division Summary:")
        print("  " + "-" * 55)
        for div in ['FMD', 'IND', 'EDR', 'BEK', 'VIC']:
            total_km = 0.0
            total_pts = 0.0
            for week_data in weekly_data.get(div, {}).values():
                for cat_data in week_data.values():
                    total_km += cat_data.get('mileage', 0)
                    total_pts += cat_data.get('points', 0)
            print(f"  {div}: {total_km:6.1f} km | {total_pts:6.2f} pts | Weighted 60%: {total_pts * 0.6:6.2f}")
        print("  " + "-" * 55)
    else:
        print("  No data to score (empty activities or missing divisions)")

    # --- Step 6: Update Google Sheets ---
    if not args.no_sheets and google_api_key and sheet_id and sheet_id != 'your_google_sheet_id_here':
        print("\n[6] Updating Google Sheets...")
        service = get_sheets_service(google_api_key)

        # Sports Challenge tab (main output)
        if weekly_data:
            write_sports_challenge_sheet(
                service=service,
                sheet_id=sheet_id,
                sheet_name='Sports Challenge',
                weekly_data=weekly_data,
            )
            print("  Updated 'Sports Challenge' sheet")

        # Individual Leaderboard tab
        if not activities_df.empty and division_teams:
            individual_lb = build_individual_leaderboard(
                activities_df=activities_df,
                members_df=members_df,
                week_start_date=date_min,
            )
            if not individual_lb.empty:
                individual_lb.to_csv(os.path.join(args.output_dir, 'individual_leaderboard.csv'), index=False)
                write_google_sheet(
                    service=service,
                    sheet_id=sheet_id,
                    sheet_name='Individual Leaderboard',
                    df=individual_lb,
                )
                print(f"  Updated 'Individual Leaderboard' sheet ({len(individual_lb)} athletes)")

        # Members tab
        write_google_sheet(service=service, sheet_id=sheet_id, sheet_name='Members', df=members_df)
        print("  Updated 'Members' sheet")

        # Activities tab (incremental)
        if not activities_df.empty:
            act_out = activities_df.copy()
            if 'activity_date' in act_out.columns:
                act_out['activity_date'] = pd.to_datetime(act_out['activity_date']).dt.strftime('%Y-%m-%d')
            update_google_sheet_incremental(
                service=service,
                sheet_id=sheet_id,
                sheet_name='Activities',
                df_new=act_out,
                key_columns=['club_id', 'activity_id'],
            )
            print("  Updated 'Activities' sheet")

        # Execution time
        update_execution_time(service=service, sheet_id=sheet_id, sheet_name='Execution Time', timezone=timezone)
        print("  Updated 'Execution Time' sheet")
    else:
        print("\n[6] Skipping Google Sheets update")

    quit_driver()
    print(f"\n✓ Done! Results saved to: {args.output_dir}")


if __name__ == '__main__':
    main()
