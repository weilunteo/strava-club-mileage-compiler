"""
Strava Club Mileage Compiler - Main Entry Point

Scrapes Strava club data and compiles weekly mileage per division,
applying the multi-sport point system and updating Google Sheets.

Usage:
    python main.py                    # Interactive mode (manual Strava login)
    python main.py --headless         # Headless mode (requires credentials in config)
    python main.py --leaderboard-only # Only scrape leaderboard (faster)
    python main.py --no-sheets        # Skip Google Sheets update (local CSV only)
"""

import argparse
import configparser
import os
import random
import sys

import pandas as pd

from src.strava_scraper import (
    strava_authentication,
    strava_club_activities,
    strava_club_leaderboard,
    strava_club_members,
    quit_driver,
)
from src.scoring import (
    calculate_mileage_from_activities,
    calculate_mileage_from_leaderboard,
    build_division_summary,
    build_individual_leaderboard,
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
)


def load_config(config_path: str = None) -> configparser.ConfigParser:
    """Load configuration from config.ini."""
    config = configparser.ConfigParser()

    if config_path is None:
        # Look for config in standard locations
        locations = [
            os.path.join(os.path.dirname(__file__), 'settings', 'config.ini'),
            os.path.join(os.path.expanduser('~'), '.strava-mileage', 'config.ini'),
        ]
        for loc in locations:
            if os.path.exists(loc):
                config_path = loc
                break

    if config_path and os.path.exists(config_path):
        config.read(config_path, encoding='utf-8')
    else:
        print(f"Warning: Config file not found. Using defaults.")

    return config


def get_division_teams(config: configparser.ConfigParser) -> dict[str, list[str]] | None:
    """Parse CLUB_MEMBERS_TEAMS from config into a dictionary."""
    try:
        teams_str = config.get('STRAVA', 'CLUB_MEMBERS_TEAMS')
    except (KeyError, configparser.NoSectionError, configparser.NoOptionError):
        return None

    if not teams_str:
        return None

    # Parse format: "FMD: 12345, 67890; IND: 11111, 22222"
    teams = {}
    for team_entry in teams_str.split(';'):
        team_entry = team_entry.strip()
        if ':' not in team_entry:
            continue
        team_name, athlete_ids_str = team_entry.split(':', 1)
        team_name = team_name.strip()
        athlete_ids = [aid.strip() for aid in athlete_ids_str.split(',')]
        teams[team_name] = athlete_ids

    return teams


def main():
    parser_arg = argparse.ArgumentParser(description='Strava Club Mileage Compiler')
    parser_arg.add_argument('--config', type=str, help='Path to config.ini')
    parser_arg.add_argument('--headless', action='store_true', help='Run browser in headless mode')
    parser_arg.add_argument(
        '--leaderboard-only',
        action='store_true',
        help='Only scrape leaderboard (faster, but no activity-type breakdown)',
    )
    parser_arg.add_argument('--no-sheets', action='store_true', help='Skip Google Sheets update')
    parser_arg.add_argument('--output-dir', type=str, default='output', help='Output directory for CSVs')
    args = parser_arg.parse_args()

    # Load config
    config = load_config(args.config)

    # Extract settings
    date_min = config.get('GENERAL', 'DATE_MIN', fallback='2026-07-21')
    date_max = config.get('GENERAL', 'DATE_MAX', fallback='2026-09-07')
    timezone = config.get('GENERAL', 'TIMEZONE', fallback='Asia/Singapore')
    club_ids = config.get('STRAVA', 'CLUB_IDS', fallback='2231427').split(', ')
    strava_login = config.get('STRAVA', 'LOGIN', fallback='')
    strava_password = config.get('STRAVA', 'PASSWORD', fallback='')
    scrap_activities = config.getboolean('GENERAL', 'SCRAP_CLUB_ACTIVITIES', fallback=True)

    # Scoring config
    scoring_config = {
        'swim_km_per_point': config.getfloat('SCORING', 'SWIM_KM_PER_POINT', fallback=2.0),
        'run_km_per_point': config.getfloat('SCORING', 'RUN_KM_PER_POINT', fallback=10.0),
        'bike_km_per_point': config.getfloat('SCORING', 'BIKE_KM_PER_POINT', fallback=40.0),
    }
    strava_weightage = config.getfloat('SCORING', 'STRAVA_WEIGHTAGE', fallback=0.60)
    ippt_weightage = config.getfloat('SCORING', 'IPPT_WEIGHTAGE', fallback=0.40)

    # Google Sheets config
    sheet_id = config.get('GOOGLE_DOCS', 'SHEET_ID', fallback='')
    google_api_key = os.path.join(os.path.dirname(__file__), 'settings', 'keys.json')
    if not os.path.exists(google_api_key):
        google_api_key = None

    # Division teams
    division_teams = get_division_teams(config)

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    print("=" * 60)
    print("STRAVA CLUB MILEAGE COMPILER")
    print("=" * 60)
    print(f"Club IDs: {club_ids}")
    print(f"Date range: {date_min} to {date_max}")
    print(f"Timezone: {timezone}")
    print(f"Divisions configured: {list(division_teams.keys()) if division_teams else 'None (set CLUB_MEMBERS_TEAMS in config)'}")
    print(f"Point system: Swim {scoring_config['swim_km_per_point']}km=1pt, Run {scoring_config['run_km_per_point']}km=1pt, Bike {scoring_config['bike_km_per_point']}km=1pt")
    print("=" * 60)

    # --- Step 1: Authenticate to Strava ---
    print("\n[1/5] Authenticating to Strava...")
    login_mode = 'credentials' if strava_login and strava_password and strava_login != 'your_email@example.com' else 'user'
    driver = strava_authentication(
        strava_login=strava_login,
        strava_password=strava_password,
        headless=args.headless,
        login_mode=login_mode,
    )

    # --- Step 2: Scrape Club Members ---
    print("\n[2/5] Scraping club members...")
    members_df = strava_club_members(
        club_ids=club_ids,
        club_members_teams=division_teams,
        timezone=timezone,
    )
    print(f"  Found {len(members_df)} members")
    if division_teams:
        assigned = members_df[members_df['athlete_team'].notna()]
        print(f"  {len(assigned)} members assigned to divisions")
        for div in ['FMD', 'IND', 'EDR', 'BEK', 'VIC']:
            count = len(assigned[assigned['athlete_team'].str.contains(div, na=False)])
            print(f"    {div}: {count} members")

    members_df.to_csv(os.path.join(args.output_dir, 'members.csv'), index=False)

    # --- Step 2b: Random Division Assignment (if no teams configured) ---
    if not division_teams and not members_df.empty:
        print("\n  No division assignments found in config. Randomly assigning members to divisions...")
        divisions = ['FMD', 'IND', 'EDR', 'BEK', 'VIC']
        unique_athletes = members_df['athlete_id'].unique().tolist()
        random.seed(42)  # Fixed seed for reproducibility
        random.shuffle(unique_athletes)

        # Distribute as evenly as possible across 5 divisions
        division_assignments = {}
        for i, athlete_id in enumerate(unique_athletes):
            div = divisions[i % len(divisions)]
            if div not in division_assignments:
                division_assignments[div] = []
            division_assignments[div].append(athlete_id)

        # Apply to members_df
        athlete_to_div = {}
        for div, ids in division_assignments.items():
            for aid in ids:
                athlete_to_div[aid] = div

        members_df['athlete_team'] = members_df['athlete_id'].map(athlete_to_div)
        division_teams = division_assignments

        print(f"  Randomly assigned {len(unique_athletes)} members to {len(divisions)} divisions:")
        for div in divisions:
            count = len(division_assignments.get(div, []))
            print(f"    {div}: {count} members")

        # Save the assignments for reference
        assignments_df = pd.DataFrame([
            {'division': div, 'athlete_id': aid}
            for div, ids in division_assignments.items()
            for aid in ids
        ])
        assignments_df = assignments_df.merge(
            members_df[['athlete_id', 'athlete_name']].drop_duplicates(),
            on='athlete_id',
            how='left',
        )
        assignments_df.to_csv(os.path.join(args.output_dir, 'division_assignments.csv'), index=False)
        print(f"  Saved assignments to {args.output_dir}/division_assignments.csv")

    members_df.to_csv(os.path.join(args.output_dir, 'members.csv'), index=False)

    # --- Step 3: Scrape Leaderboard ---
    print("\n[3/5] Scraping club leaderboard...")
    leaderboard_df = strava_club_leaderboard(
        club_ids=club_ids,
        filter_date_min=date_min,
        filter_date_max=date_max,
        timezone=timezone,
    )
    print(f"  Scraped {len(leaderboard_df)} leaderboard entries")
    leaderboard_df.to_csv(os.path.join(args.output_dir, 'leaderboard.csv'), index=False)

    # --- Step 4: Scrape Activities (if enabled) ---
    activities_df = pd.DataFrame()
    if scrap_activities and not args.leaderboard_only:
        print("\n[4/5] Scraping individual activities (this may take a while)...")
        new_activities_df = strava_club_activities(
            club_ids=club_ids,
            filter_activities_type=None,  # Get all types for multi-sport scoring
            filter_date_min=date_min,
            filter_date_max=date_max,
            timezone=timezone,
        )
        print(f"  Scraped {len(new_activities_df)} new activities")

        # Merge with existing activities (keep history from previous runs)
        existing_path = os.path.join(args.output_dir, 'activities.csv')
        if os.path.exists(existing_path):
            existing_df = pd.read_csv(existing_path, dtype=str)
            activities_df = pd.concat([existing_df, new_activities_df], ignore_index=True)
            activities_df = activities_df.drop_duplicates(subset=['activity_id'], keep='last', ignore_index=True)
            print(f"  Merged with existing: {len(activities_df)} total activities (history preserved)")
        else:
            activities_df = new_activities_df

        if not activities_df.empty:
            activities_df.to_csv(existing_path, index=False)
    else:
        print("\n[4/5] Skipping individual activities scrape")
        # Still load existing activities for scoring
        existing_path = os.path.join(args.output_dir, 'activities.csv')
        if os.path.exists(existing_path):
            activities_df = pd.read_csv(existing_path, dtype=str)
            print(f"  Loaded {len(activities_df)} activities from history")

    # --- Step 5: Calculate Scores ---
    print("\n[5/5] Calculating scores...")

    if not activities_df.empty and division_teams:
        # Use individual activities for accurate multi-sport scoring
        weekly_scores = calculate_mileage_from_activities(
            activities_df=activities_df,
            members_df=members_df,
            config=scoring_config,
        )
        print("  Using individual activities for multi-sport point calculation")

        # Build individual leaderboard
        individual_lb = build_individual_leaderboard(
            activities_df=activities_df,
            members_df=members_df,
            config=scoring_config,
        )
        if not individual_lb.empty:
            individual_lb.to_csv(os.path.join(args.output_dir, 'individual_leaderboard.csv'), index=False)
            print(f"  Individual leaderboard: {len(individual_lb)} athletes")

    elif not leaderboard_df.empty and division_teams:
        # Fall back to leaderboard data (no activity type breakdown)
        weekly_scores = calculate_mileage_from_leaderboard(
            leaderboard_df=leaderboard_df,
            members_df=members_df,
            config=scoring_config,
        )
        print("  Using leaderboard data (run-equivalent points, no sport breakdown)")
    else:
        weekly_scores = pd.DataFrame()
        print("  No data available for scoring (check division assignments)")

    if not weekly_scores.empty:
        weekly_scores.to_csv(os.path.join(args.output_dir, 'weekly_scores.csv'), index=False)

        # Build division summary
        summary = build_division_summary(
            weekly_division_df=weekly_scores,
            ippt_data=None,  # IPPT data managed in Google Sheets manually
            strava_weightage=strava_weightage,
            ippt_weightage=ippt_weightage,
        )
        summary.to_csv(os.path.join(args.output_dir, 'division_summary.csv'), index=False)
        print("\n  Division Summary:")
        print("  " + "-" * 50)
        for _, row in summary.iterrows():
            print(f"  {row['division']}: {row['total_mileage_km']:.1f} km | {row['strava_sub_points']:.2f} pts | Weighted: {row['strava_weighted']:.2f}")
        print("  " + "-" * 50)

    # --- Step 6: Update Google Sheets ---
    if not args.no_sheets and google_api_key and sheet_id and sheet_id != 'your_google_sheet_id_here':
        print("\n[6] Updating Google Sheets...")
        service = get_sheets_service(google_api_key)

        # Write the formatted 'Sports Challenge' sheet (pink section only)
        if not activities_df.empty and division_teams:
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
            print("  Updated 'Sports Challenge' sheet (weekly mileage section)")

        # Update Members sheet (overwritten - current member list)
        write_google_sheet(service=service, sheet_id=sheet_id, sheet_name='Members', df=members_df)
        print("  Updated 'Members' sheet")

        # Update Leaderboard sheet (incremental)
        if not leaderboard_df.empty:
            leaderboard_out = leaderboard_df.copy()
            leaderboard_out['leaderboard_date_start'] = leaderboard_out['leaderboard_date_start'].dt.strftime('%Y-%m-%d')
            leaderboard_out['leaderboard_date_end'] = leaderboard_out['leaderboard_date_end'].dt.strftime('%Y-%m-%d')
            update_google_sheet_incremental(
                service=service,
                sheet_id=sheet_id,
                sheet_name='Leaderboard',
                df_new=leaderboard_out,
                key_columns=['club_id', 'leaderboard_week', 'athlete_id'],
            )
            print("  Updated 'Leaderboard' sheet (incremental)")

        # Update Activities sheet (incremental)
        if not activities_df.empty:
            activities_out = activities_df.copy()
            if 'activity_date' in activities_out.columns:
                activities_out['activity_date'] = pd.to_datetime(activities_out['activity_date']).dt.strftime('%Y-%m-%d')
            update_google_sheet_incremental(
                service=service,
                sheet_id=sheet_id,
                sheet_name='Activities',
                df_new=activities_out,
                key_columns=['club_id', 'activity_id'],
            )
            print("  Updated 'Activities' sheet (incremental)")

        # Update Weekly Scores sheet
        if not weekly_scores.empty:
            write_google_sheet(
                service=service, sheet_id=sheet_id, sheet_name='Weekly Scores', df=weekly_scores
            )
            print("  Updated 'Weekly Scores' sheet")

        # Update Division Summary sheet
        if not weekly_scores.empty:
            write_google_sheet(
                service=service, sheet_id=sheet_id, sheet_name='Division Summary', df=summary
            )
            print("  Updated 'Division Summary' sheet")

        # Update execution time
        update_execution_time(
            service=service, sheet_id=sheet_id, sheet_name='Execution Time', timezone=timezone
        )
        print("  Updated 'Execution Time' sheet")
    else:
        print("\n[6] Skipping Google Sheets update (not configured or --no-sheets)")

    # Cleanup
    quit_driver()
    print("\n✓ Done! Results saved to:", args.output_dir)


if __name__ == '__main__':
    main()
