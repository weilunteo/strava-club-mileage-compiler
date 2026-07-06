# Strava Club Mileage Compiler

Automated weekly mileage compilation for an inter-division fitness competition (51 participants across 5 divisions), scraping data from a Strava Club and updating a Google Sheet.

## Overview

This script does not use the Strava API (which requires a paid subscription for club activity data). Instead, it uses Selenium web scraping to extract activity data directly from the Strava website.

This script:
1. Opens Chrome and waits for manual Strava login (2FA required)
2. Scrapes the club's individual activities (run, walk, hike)
3. Assigns athletes to divisions (FMD, IND, EDR, BEK, VIC)
4. Calculates weekly mileage and points per division
5. Writes the results directly into a formatted Google Sheet

## Point System

| Activity | Distance for 1 Point | Time Equivalent |
|----------|---------------------|-----------------|
| Run / Walk / Hike | 10 km | ~60 minutes |

No cap on points — allows catching up.

## Competition Scoring

| Component | Weightage |
|-----------|-----------|
| IPPT | 40% (Gold = 3 pts, Silver = 1 pt) — managed manually in sheet |
| Weekly Strava Mileage | 60% — calculated by this script |

## Divisions

| Division | Members |
|----------|---------|
| FMD | ~10 |
| IND | ~10 |
| EDR | ~10 |
| BEK | ~10 |
| VIC | ~10 |

## Competition Period

- **Week 3**: 13 Jul 2026 (Mon) – 19 Jul 2026 (Sun)
- **Week 4**: 20 Jul 2026 – 26 Jul 2026
- ...
- **Week 23**: 30 Nov 2026 – 6 Dec 2026 (Sun)

## Google Sheet Layout

The script writes ONLY to the pink "Weekly Strava Mileage" section (cells C7:L30):

| Section | Rows | Managed by |
|---------|------|-----------|
| IPPT (green) | 1-5 | Manual |
| Weekly Mileage headers | 6 | Fixed (don't touch) |
| Week 3-23 data | 7-27 | **Script** |
| Total / Sub Total / Weightage 60% | 28-30 | **Script** |
| Total Points (yellow) | 31 | Your formula (IPPT + Strava) |
| Total Batch Mileage (yellow) | 32 | Your formula |

## Strava Club

- Type: Multisport
- Club ID and URL are configured privately in `settings/config.ini` (not committed to this repo)

---

## For the Operator (Weekly Runner)

### What you need
- A Mac/PC with **Python 3** and **Google Chrome** installed
- Be a member of the Strava club
- Access to the email associated with the Strava account (for verification codes)

### How to run (every Monday)

1. **Double-click** `run.command`
2. Chrome opens → **Log in to Strava** (email + 6-digit code from your email)
3. Wait for **"✓ DONE!"** message (~3-5 minutes)
4. Check the Google Sheet — data is updated!

### Troubleshooting

| Problem | Solution |
|---------|----------|
| "Access temporarily suspended" | Strava rate-limited you. Wait 15 min, try again |
| Chrome doesn't open | Make sure Chrome is installed |
| Script hangs at "Waiting for dashboard" | Go log in to Strava in the Chrome window |
| Google Sheets "protected cell" error | Ask Wei Liang to fix sheet permissions |
| "No module named..." | Open Terminal, run: `pip3 install -r requirements.txt` |

---

## For the Developer

### Project Structure

```
strava-club-mileage-compiler/
├── main.py                  # Main entry point
├── push_to_sheets.py        # Push existing data without re-scraping
├── clear_sheets.py          # Clear Google Sheets test data
├── run.command              # One-click run script for operator
├── HOW_TO_RUN.md            # Instructions for the operator
├── requirements.txt         # Python dependencies
├── Dockerfile               # For Docker/Railway deployment
├── settings/
│   ├── config.ini           # Configuration (dates, club ID, divisions, scoring)
│   ├── config.ini.example   # Template
│   └── keys.json            # Google Service Account key (DO NOT COMMIT)
├── src/
│   ├── __init__.py
│   ├── strava_scraper.py    # Selenium-based Strava scraper
│   ├── scoring.py           # Multi-sport point calculation engine
│   ├── google_sheets.py     # Google Sheets API helpers
│   ├── sheets_formatter.py  # Formats data into competition layout
│   └── selenium_utils.py    # Chrome WebDriver setup
├── output/                  # Accumulated CSV data (history)
│   ├── activities.csv       # All activities (grows each week)
│   ├── members.csv          # Current member list
│   └── ...
└── .github/workflows/
    └── scrape.yml           # GitHub Actions (not usable due to Strava 2FA)
```

### Configuration

Edit `settings/config.ini`:

```ini
[GENERAL]
DATE_MIN = 2026-07-13          # Monday of Week 3
DATE_MAX = 2026-12-06          # Sunday of Week 23
TIMEZONE = Asia/Singapore
SCRAP_CLUB_ACTIVITIES = true

[STRAVA]
CLUB_IDS = <your_club_id>
# Division assignments (populate with athlete IDs):
CLUB_MEMBERS_TEAMS = FMD: id1, id2; IND: id3, id4; EDR: id5; BEK: id6; VIC: id7

[GOOGLE_DOCS]
SHEET_ID = <your_sheet_id>

[SCORING]
RUN_KM_PER_POINT = 10.0
```

### Setting Up Divisions

1. Run the script once to scrape members → check `output/members.csv` for athlete IDs
2. Assign each athlete to a division in `config.ini` under `CLUB_MEMBERS_TEAMS`
3. Format: `FMD: 12345, 67890; IND: 11111, 22222; EDR: 33333; BEK: 44444; VIC: 55555`

If `CLUB_MEMBERS_TEAMS` is not set, the script randomly assigns members to divisions.

### Google Sheets Setup

1. Enable [Google Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com)
2. Create a Service Account → download JSON key → save as `settings/keys.json`
3. Share the Google Sheet with your service account's email (Editor access) — find this in your `keys.json` under `client_email`

### Data Persistence

- `output/activities.csv` accumulates all activities across weeks (never loses history)
- Each run merges new activities with existing ones (deduplicates by activity_id)
- The Sports Challenge sheet always shows Week 3-23 calculated from ALL accumulated data

### Command Line Options

```bash
python main.py                    # Full run (scrape + update sheets)
python main.py --no-sheets        # Scrape only, save CSVs locally
python main.py --leaderboard-only # Skip individual activities
python main.py --headless         # No browser GUI (won't work with 2FA)
python push_to_sheets.py          # Push existing CSV data to sheets (no Strava)
python clear_sheets.py            # Clear all Google Sheets data
```

### Limitations

- **Strava 2FA**: Requires manual login every run (email verification code). Full automation is not possible.
- **Activity feed limit**: Strava limits how far back you can scroll in the club feed. Run weekly to avoid missing activities.
- **Rate limiting**: Too many login attempts → "temporarily suspended". Wait 15 minutes.
- **Leaderboard**: Only shows current + previous week. Individual activities are more reliable for historical data.

## Legal

Web scraping may not comply with Strava's Terms of Service. Use at your own risk.

Adapted from [strava-club-scraper](https://github.com/roboes/strava-club-scraper).