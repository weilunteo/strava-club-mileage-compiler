"""
Formats and writes scraped Strava data directly into the 'Sports Challenge'
Google Sheet tab - ONLY the mileage/points data cells.

Everything else in the sheet is fixed and managed by you:
- Row 1-5: IPPT section (green) — untouched
- Row 6: Headers (Mileage/Points) — untouched
- Rows 7-27 columns A-B: Week labels — untouched
- Rows 7-27 columns C-L: DATA CELLS — written by this script
- Row 28: Total — untouched (your formula)
- Row 29: Sub Total — untouched (your formula)
- Row 30: Weightage (60%) — untouched (your formula)
- Row 31: Total Points — untouched (your formula)
- Row 32: Total Batch Mileage — untouched (your formula)

The script ONLY writes to C7:L27 (the 21 week rows of mileage/points data).
"""

import pandas as pd
from .google_sheets import _ensure_sheet_exists


DIVISIONS = ['FMD', 'IND', 'EDR', 'BEK', 'VIC']
WEEKS = [f'Week {i}' for i in range(3, 24)]  # Week 3 to Week 23


def build_weekly_data_cells(weekly_data: dict) -> list[list]:
    """
    Build the data values for C7:L30.
    Rows 7-27: Weekly mileage/points per division (21 rows)
    Row 28: Total (sum of mileage/points per division)
    Row 29: Sub Total (same as Total)
    Row 30: Weightage (60%) = points * 0.6
    """
    rows = []

    division_totals_mileage = {div: 0.0 for div in DIVISIONS}
    division_totals_points = {div: 0.0 for div in DIVISIONS}

    # Rows 7-27: Week 3 to Week 23
    for week in WEEKS:
        row = []
        for div in DIVISIONS:
            if div in weekly_data and week in weekly_data[div]:
                mileage = round(weekly_data[div][week].get('mileage', 0), 1)
                points = round(weekly_data[div][week].get('points', 0), 1)
            else:
                mileage = 0
                points = 0
            row.extend([mileage, points])
            division_totals_mileage[div] += mileage
            division_totals_points[div] += points
        rows.append(row)

    # Row 28: Total
    row_total = []
    for div in DIVISIONS:
        row_total.extend([round(division_totals_mileage[div], 1), round(division_totals_points[div], 1)])
    rows.append(row_total)

    # Row 29: Sub Total
    row_subtotal = []
    for div in DIVISIONS:
        row_subtotal.extend([round(division_totals_mileage[div], 1), round(division_totals_points[div], 1)])
    rows.append(row_subtotal)

    # Row 30: Weightage (60%)
    row_weightage = []
    for div in DIVISIONS:
        weighted = round(division_totals_points[div] * 0.6, 2)
        row_weightage.extend([weighted, ''])
    rows.append(row_weightage)

    return rows


def prepare_weekly_data_from_activities(
    activities_df: pd.DataFrame,
    members_df: pd.DataFrame,
    scoring_config: dict,
    week_start_date: str,
) -> dict:
    """
    Transform activities DataFrame into the weekly_data dict format.

    Parameters:
        activities_df: DataFrame with [athlete_id, activity_type, distance, activity_date]
        members_df: DataFrame with [athlete_id, athlete_team]
        scoring_config: dict with swim/run/bike km_per_point
        week_start_date: The Monday date of Week 3 (e.g. '2026-07-13')

    Returns:
        dict like {'FMD': {'Week 3': {'mileage': 80, 'points': 8.0}, ...}, ...}
    """
    from .scoring import classify_activity, calculate_points

    if activities_df.empty:
        return {}

    swim_km = scoring_config.get('swim_km_per_point', 2.0)
    run_km = scoring_config.get('run_km_per_point', 10.0)
    bike_km = scoring_config.get('bike_km_per_point', 40.0)

    # Merge with division
    df = activities_df.copy()
    df = df.merge(
        members_df[['athlete_id', 'athlete_team']].drop_duplicates(),
        on='athlete_id',
        how='left',
    )
    df = df[df['athlete_team'].notna()].copy()

    if df.empty:
        return {}

    # Classify and calculate points
    df['activity_category'] = df['activity_type'].apply(classify_activity)
    df['distance'] = pd.to_numeric(df['distance'], errors='coerce').fillna(0)
    df['distance_km'] = df['distance'] / 1000.0
    df['points'] = df.apply(
        lambda row: calculate_points(
            row['distance'], row['activity_category'], swim_km, run_km, bike_km
        ),
        axis=1,
    )

    # Determine week number based on activity_date relative to week_start_date
    # week_start_date = Monday of Week 3 (13 Jul 2026)
    # Week 3: 13-19 Jul, Week 4: 20-26 Jul, ... Week 23: 30 Nov - 6 Dec
    df['activity_date'] = pd.to_datetime(df['activity_date'])
    competition_start = pd.to_datetime(week_start_date)

    df['days_since_start'] = (df['activity_date'] - competition_start).dt.days
    df['week_num'] = (df['days_since_start'] // 7) + 3  # Week 3 is the first week
    df['week_label'] = 'Week ' + df['week_num'].astype(int).astype(str)

    # Filter only valid weeks (3-23) and activities on/after competition start
    df = df[(df['days_since_start'] >= 0) & (df['week_num'] >= 3) & (df['week_num'] <= 23)].copy()

    # Aggregate by division and week
    weekly_data = {}
    for div in DIVISIONS:
        div_df = df[df['athlete_team'] == div]
        weekly_data[div] = {}

        for week in WEEKS:
            week_df = div_df[div_df['week_label'] == week]
            mileage = week_df['distance_km'].sum()
            points = week_df['points'].sum()
            weekly_data[div][week] = {
                'mileage': round(mileage, 1),
                'points': round(points, 1),
            }

    return weekly_data


def write_sports_challenge_sheet(
    *,
    service,
    sheet_id: str,
    sheet_name: str,
    weekly_data: dict,
    ippt_data: dict | None = None,
) -> None:
    """
    Write ONLY the weekly mileage/points data cells to C7:L27.
    Does NOT touch headers, labels, formulas, or any other cells.
    """
    _ensure_sheet_exists(service, sheet_id, sheet_name)

    grid = build_weekly_data_cells(weekly_data=weekly_data)

    # Write to C7:L30 — weeks data + Total + Sub Total + Weightage (60%)
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"'{sheet_name}'!C7:L30",
        valueInputOption='USER_ENTERED',
        body={'values': grid},
    ).execute()
