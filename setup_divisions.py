"""
One-time setup script: match roster names to Strava athlete IDs
and write the mapping into settings/config.ini.

Run this ONCE after everyone has joined the Strava club.
After this, main.py will use the saved mapping every week — no re-matching needed.

Usage:
    python setup_divisions.py                # Scrape members from Strava + match
    python setup_divisions.py --from-cache   # Use existing output/members.csv
"""

import argparse
import configparser
import json
import os
import re

import pandas as pd

from src.name_matcher import match_roster_to_strava
from src.strava_scraper import strava_authentication, strava_club_members, quit_driver


def load_config(path: str) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.read(path, encoding='utf-8')
    return config


def load_roster(path: str) -> dict[str, list[str]]:
    with open(path, 'r') as f:
        return json.load(f)


def format_teams_string(division_teams: dict[str, list[str]]) -> str:
    """Convert {'FMD': ['1', '2'], 'IND': ['3']} -> 'FMD: 1, 2; IND: 3'."""
    parts = []
    for div, ids in division_teams.items():
        if ids:
            parts.append(f"{div}: {', '.join(ids)}")
    return '; '.join(parts)


def write_teams_to_config(config_path: str, teams_string: str) -> None:
    """Update the CLUB_MEMBERS_TEAMS line in config.ini, preserving comments."""
    with open(config_path, 'r') as f:
        content = f.read()

    new_line = f"CLUB_MEMBERS_TEAMS = {teams_string}"

    # Check if the line exists (commented or not)
    if re.search(r'^#?\s*CLUB_MEMBERS_TEAMS\s*=.*$', content, re.MULTILINE):
        content = re.sub(
            r'^#?\s*CLUB_MEMBERS_TEAMS\s*=.*$',
            new_line,
            content,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        # Add it under [STRAVA] section
        content = re.sub(
            r'(\[STRAVA\][^\[]*?)(\n\[|\Z)',
            rf'\1\n{new_line}\n\2',
            content,
            count=1,
            flags=re.DOTALL,
        )

    with open(config_path, 'w') as f:
        f.write(content)


def main():
    ap = argparse.ArgumentParser(description='One-time division setup')
    ap.add_argument('--from-cache', action='store_true', help='Use output/members.csv instead of scraping')
    ap.add_argument('--threshold', type=float, default=0.5, help='Fuzzy match threshold (0-1)')
    args = ap.parse_args()

    config_path = os.path.join(os.path.dirname(__file__), 'settings', 'config.ini')
    roster_path = os.path.join(os.path.dirname(__file__), 'settings', 'roster.json')

    config = load_config(config_path)
    roster = load_roster(roster_path)

    total_expected = sum(len(names) for names in roster.values())
    print(f"Roster has {total_expected} names across {len(roster)} divisions")

    # Get member list
    members_path = os.path.join('output', 'members.csv')

    if args.from_cache and os.path.exists(members_path):
        print(f"Loading members from cache: {members_path}")
        members_df = pd.read_csv(members_path, dtype=str)
    else:
        print("Scraping members from Strava...")
        strava_authentication(
            strava_login=config.get('STRAVA', 'LOGIN', fallback=''),
            strava_password=config.get('STRAVA', 'PASSWORD', fallback=''),
            headless=False,
            login_mode='user',
        )
        club_ids = config.get('STRAVA', 'CLUB_IDS').split(', ')
        timezone = config.get('GENERAL', 'TIMEZONE', fallback='Asia/Singapore')
        members_df = strava_club_members(
            club_ids=club_ids,
            club_members_teams=None,
            timezone=timezone,
        )
        os.makedirs('output', exist_ok=True)
        members_df.to_csv(members_path, index=False)
        quit_driver()

    print(f"Found {len(members_df)} Strava members\n")

    # Fuzzy match
    strava_members = members_df[['athlete_id', 'athlete_name']].to_dict('records')
    division_teams, unmatched = match_roster_to_strava(
        roster, strava_members, threshold=args.threshold
    )

    # Show matched results
    print("=" * 60)
    print("MATCHED (verify these look correct):")
    print("=" * 60)
    name_lookup = dict(zip(members_df['athlete_id'], members_df['athlete_name']))
    for div in ['FMD', 'IND', 'EDR', 'BEK', 'VIC']:
        expected = len(roster.get(div, []))
        matched_ids = division_teams.get(div, [])
        print(f"\n  {div}: {len(matched_ids)}/{expected} matched")
        for aid in matched_ids:
            print(f"    {name_lookup.get(aid, '?')} (id: {aid})")

    # Show unmatched
    if unmatched:
        print("\n" + "=" * 60)
        print("NOT MATCHED (probably not on Strava yet, or name too different):")
        print("=" * 60)
        for entry in unmatched:
            best = entry.get('best_match_name') or '(none)'
            print(f"  [{entry['division']}] {entry['roster_name']} — closest guess: {best} (score {entry['score']})")
        pd.DataFrame(unmatched).to_csv(os.path.join('output', 'unmatched_roster.csv'), index=False)
        print(f"\n  Details saved to output/unmatched_roster.csv")

    # Write to config
    teams_string = format_teams_string(division_teams)
    write_teams_to_config(config_path, teams_string)

    print("\n" + "=" * 60)
    print(f"✓ Written to {config_path}")
    print("=" * 60)
    print("\nEvery weekly run of main.py will now use these fixed mappings.")
    print("Re-run this script if roster.json or Strava membership changes.")


if __name__ == '__main__':
    main()
