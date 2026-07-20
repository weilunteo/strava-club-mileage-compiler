# Strava Club Mileage Compiler

Automated weekly mileage compilation for an inter-division fitness competition, scraping data from a Strava Club and updating a Google Sheet.

## Overview

This script does not use the Strava API (which requires a paid subscription for club data). Instead, it uses Selenium web scraping to extract activity data directly from Strava.

What it does:
1. Opens Chrome and waits for manual Strava login (2FA required)
2. Scrapes the club's members and individual activities
3. Maps athletes to divisions (using a name-based roster)
4. Classifies each activity (Run, Walk, Swim, Bike) using activity type + pace
5. Calculates weekly mileage & points per division per activity type
6. Writes results to a formatted 'Sports Challenge' Google Sheet + 'Individual Leaderboard'

## Point System

| Activity | Rate | Distance for 1 pt |
|----------|------|-------------------|
| Run (pace < 9 min/km) | 0.10 pt/km | 10 km |
| Walk (pace ≥ 9 min/km) | 0.05 pt/km | 20 km |
| Swim | 0.50 pt/km | 2 km |
| Bike | 0.025 pt/km | 40 km |

Run vs Walk is determined automatically from the activity's moving pace. Applies to: Run, Trail Run, Treadmill, Virtual Run, Walk, Hike, Race.

## Competition Scoring

| Component | Weightage |
|-----------|-----------|
| IPPT | 40% (managed manually in sheet) |
| Weekly Strava Mileage | 60% (calculated by this script) |

## Google Sheet Layout

The script writes to three tabs:

### Sports Challenge (main tab)
- Rows 1-5 (IPPT section): untouched
- Row 6 (headers): untouched
- Rows 7-27 (Week 3 to Week 23): weekly mileage & points per division per activity type (Run, Walk, Swim, Bike)
- Row 28 (Sub Total): computed by script
- Row 29 (Mileage Points): total points per division, computed by script
- Rows 30-32 (Weightage 60%, Total Points, Total Batch Mileage): untouched (your formulas)

Data range written: `C7:AP29`

### Individual Leaderboard
Per-athlete breakdown across all 4 categories, sorted by total points:
- rank, division, athlete_name, athlete_id
- run_km, run_pts, walk_km, walk_pts, swim_km, swim_pts, bike_km, bike_pts
- total_km, total_points, num_activities

### Activities
Incremental raw activity log — grows every week, deduped by activity_id.

### Members
Current club member list with division assignments.

### Execution Time
Last-run timestamp.

## Project Structure

```
strava-club-mileage-compiler/
├── main.py                  # Weekly runner
├── setup_divisions.py       # ONE-TIME: match roster to Strava, save to config
├── push_to_sheets.py        # Push cached data to Sheets (no scraping)
├── run.command              # Double-click helper for weekly runs
├── requirements.txt
├── README.md
├── .gitignore
├── settings/
│   ├── config.ini           # Configuration (dates, club ID, scoring)
│   ├── roster.json          # Division roster (names only)
│   └── keys.json            # Google service account key (NOT committed)
├── src/
│   ├── strava_scraper.py    # Selenium scraper for Strava
│   ├── scoring.py           # Point calculation (pace-based run/walk)
│   ├── sheets_formatter.py  # Formats data for Google Sheets
│   ├── google_sheets.py     # Google Sheets API helpers
│   ├── name_matcher.py      # Fuzzy roster-to-Strava name matcher (rapidfuzz)
│   └── selenium_utils.py    # Chrome WebDriver config
└── output/                  # Accumulated CSV history (grows each week)
```

## Setup (One Time)

### 1. Prerequisites
- Python 3.10+
- Google Chrome
- A Strava account that's a member of the club

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure `settings/config.ini`

```ini
[GENERAL]
DATE_MIN = 2026-07-13     # Monday of Week 3
DATE_MAX = 2026-12-06     # Sunday of Week 23
TIMEZONE = Asia/Singapore
SCRAP_CLUB_ACTIVITIES = true

[STRAVA]
LOGIN = your_email@example.com
PASSWORD = your_password
CLUB_IDS = <your-strava-club-id>

[GOOGLE_DOCS]
SHEET_ID = <your-google-sheet-id>

[SCORING]
IPPT_WEIGHTAGE = 0.40
STRAVA_WEIGHTAGE = 0.60
```

### 4. Configure `settings/roster.json`

List all participants by name under their divisions:

```json
{
  "FMD": ["Name 1", "Name 2", "..."],
  "IND": ["..."],
  "EDR": ["..."],
  "BEK": ["..."],
  "VIC": ["..."]
}
```

### 5. Set up Google Sheets API

1. Enable [Google Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com)
2. Create a Service Account → download JSON key → save as `settings/keys.json`
3. Share the Google Sheet with the service account email (Editor access)

### 6. Match roster to Strava (once, when everyone's joined)

```bash
python setup_divisions.py
```

This:
- Scrapes current Strava club members
- Fuzzy-matches roster names → Strava athlete IDs
- Writes `CLUB_MEMBERS_TEAMS = ...` into `config.ini`
- Reports unmatched names (people not yet on Strava)

Re-run this whenever new members join the club.

## Weekly Run

### Option A — Double-click (for non-technical users)
Double-click `run.command`. Chrome opens → log in to Strava → wait for "Done!".

### Option B — Command line
```bash
python main.py
```

The weekly flow:
1. Opens Chrome → wait for manual Strava login
2. Scrapes members (deduplicates against cache)
3. Scrapes leaderboard + individual activities
4. Merges with cached `output/activities.csv` (preserves history)
5. Calculates weekly points and writes to Google Sheet

### Command line options

```bash
python main.py                    # Full run (scrape + push to sheets)
python main.py --no-sheets        # Scrape only, save CSVs locally
python main.py --leaderboard-only # Skip individual activities
python push_to_sheets.py          # Push cached data (no Strava scrape)
```

## Fuzzy Name Matching

Roster names often differ from Strava display names (nicknames, initials, reversed order, concatenated names). The matcher handles:

- Reordered names (First Middle Last ↔ Last First Middle)
- Concatenated names (Wei Xiang ↔ Weixiang)
- Partial names / nicknames (extra middle names, dropped suffixes)
- Initials (Full Name ↔ Initials, or `F Lastname`)

Uses [rapidfuzz](https://github.com/rapidfuzz/RapidFuzz) with a custom initials heuristic. Threshold defaults to 0.7.

## Data Persistence

- `output/activities.csv` accumulates all scraped activities across weeks (deduped by `activity_id`)
- `output/members.csv` reflects the latest scraped member list
- The 'Sports Challenge' tab always recalculates from the full accumulated history

**Do not delete `output/activities.csv`** — it's your competition history. Strava's feed only shows recent activities, so weekly scraping + local accumulation is how history is preserved.

## Limitations

- **Strava 2FA**: Requires manual email verification code on each run. No headless automation.
- **Activity feed limit**: Strava caps how far back you can scroll. Run at least weekly to avoid missing activities.
- **Rate limiting**: Too many login attempts → account temporarily suspended. Wait ~15 minutes.
- **Leaderboard**: Only shows current + previous week and doesn't distinguish activity types. Individual activities are used instead for accurate multi-sport scoring.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Access temporarily suspended" | Strava rate-limited. Wait 15 minutes. |
| Chrome doesn't open | Make sure Chrome is installed. |
| "No module named ..." | Run `pip install -r requirements.txt` |
| Google Sheets "protected cell" error | Remove sheet protection or add service account to editors. |
| Members sheet has fewer names than expected | Some roster members haven't joined the Strava club yet. Re-run `setup_divisions.py`. |
| Unmatched roster names after setup | Person may have a very different Strava display name — check `output/unmatched_roster.csv`. |

## Legal

Web scraping may not comply with Strava's Terms of Service. Use at your own risk.

Adapted from [strava-club-scraper](https://github.com/roboes/strava-club-scraper).
