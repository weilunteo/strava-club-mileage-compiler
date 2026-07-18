"""
Formats and writes scraped Strava data into the 'Sports Challenge' Google Sheet.

New sheet layout (per division: Run | Walk | Swim | Bike, each with Mileage + Points):

  Cols per division = 8 (Run.mi, Run.pt, Walk.mi, Walk.pt, Swim.mi, Swim.pt, Bike.mi, Bike.pt)
  Total data cols = 5 divisions × 8 = 40

  Row 6: Sub-headers (Run/Walk/Swim/Bike x Mileage/Points) - fixed in sheet
  Rows 7-27: Week 3 through Week 23 (data written here)
  Row 28: Sub Total (mileage/points per activity type per division)
  Row 29: Mileage Points (sum of points per division, one column each)
  Row 30: Weightage (60%) — your formula (untouched)
  Row 31: Total Points — your formula (untouched)
  Row 32: Total Batch Mileage — your formula (untouched)

The script writes ONLY the data cells (weekly mileage/points + Sub Total + Mileage Points).
Column ranges depend on your final sheet layout — configured below.
"""

import pandas as pd
from .google_sheets import _ensure_sheet_exists
from .scoring import classify_activity, calculate_points


DIVISIONS = ['FMD', 'IND', 'EDR', 'BEK', 'VIC']
CATEGORIES = ['run', 'walk', 'swim', 'bike']  # Order matches sheet columns per division
WEEKS = [f'Week {i}' for i in range(3, 24)]  # Week 3 to Week 23

# Data starts at column C (col A/B are labels)
# Each division = 8 columns (4 categories × 2 [mileage, points])
DATA_START_COL = 'C'
DATA_END_COL_INDEX = 2 + (len(DIVISIONS) * len(CATEGORIES) * 2) - 1  # 0-indexed, col A=0
# 2 + 40 - 1 = 41 -> column index 41 = "AP"

# Row ranges
FIRST_WEEK_ROW = 7   # Week 3
LAST_WEEK_ROW = 27   # Week 23
SUB_TOTAL_ROW = 28
MILEAGE_POINTS_ROW = 29


def _col_letter(idx: int) -> str:
    """Convert 0-indexed column number to letter (0=A, 25=Z, 26=AA)."""
    result = ''
    n = idx
    while True:
        result = chr(ord('A') + (n % 26)) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result


DATA_END_COL = _col_letter(DATA_END_COL_INDEX)


def build_weekly_rows(weekly_data: dict) -> list[list]:
    """
    Build rows for Week 3 to Week 23 + Sub Total + Mileage Points row.

    weekly_data[division][week][category] = {'mileage': X, 'points': Y}
    """
    rows = []

    # Running totals per division per category
    totals = {
        div: {cat: {'mileage': 0.0, 'points': 0.0} for cat in CATEGORIES}
        for div in DIVISIONS
    }

    # Rows 7-27: weekly data
    for week in WEEKS:
        row = []
        for div in DIVISIONS:
            for cat in CATEGORIES:
                cell = weekly_data.get(div, {}).get(week, {}).get(cat, {})
                mileage = round(cell.get('mileage', 0), 1)
                points = round(cell.get('points', 0), 2)
                row.extend([mileage, points])
                totals[div][cat]['mileage'] += mileage
                totals[div][cat]['points'] += points
        rows.append(row)

    # Row 28: Sub Total per category per division
    row_subtotal = []
    for div in DIVISIONS:
        for cat in CATEGORIES:
            row_subtotal.extend([
                round(totals[div][cat]['mileage'], 1),
                round(totals[div][cat]['points'], 2),
            ])
    rows.append(row_subtotal)

    # Row 29: Mileage Points = sum of all category points per division
    #   Layout per division (8 cols): we put the total in the first cell, others blank
    #   Actually, from your image "Mileage Points" appears as a single number per division.
    #   So we put the sum in the first column of each division and leave the rest blank.
    row_mileage_points = []
    for div in DIVISIONS:
        div_total_points = sum(totals[div][cat]['points'] for cat in CATEGORIES)
        row_mileage_points.append(round(div_total_points, 2))
        # Fill remaining 7 cols with empty string
        row_mileage_points.extend([''] * 7)
    rows.append(row_mileage_points)

    return rows


def prepare_weekly_data_from_activities(
    activities_df: pd.DataFrame,
    members_df: pd.DataFrame,
    week_start_date: str,
    scoring_config: dict = None,  # kept for backward compatibility, unused now
) -> dict:
    """
    Transform activities into: {division: {week: {category: {mileage, points}}}}

    Uses activity pace to distinguish Run vs Walk (>=9 min/km => Walk).
    """
    if activities_df.empty:
        return {}

    df = activities_df.copy()

    # Merge with division
    df = df.merge(
        members_df[['athlete_id', 'athlete_team']].drop_duplicates(),
        on='athlete_id',
        how='left',
    )
    df = df[df['athlete_team'].notna()].copy()
    if df.empty:
        return {}

    # Numeric columns
    df['distance'] = pd.to_numeric(df['distance'], errors='coerce').fillna(0)
    df['moving_time'] = pd.to_numeric(df.get('moving_time', 0), errors='coerce').fillna(0)
    df['distance_km'] = df['distance'] / 1000.0

    # Classify with pace-based rule
    df['activity_category'] = df.apply(
        lambda row: classify_activity(row['activity_type'], row['distance'], row['moving_time']),
        axis=1,
    )

    # Calculate points
    df['points'] = df.apply(
        lambda row: calculate_points(row['distance'], row['activity_category']),
        axis=1,
    )

    # Week number
    df['activity_date'] = pd.to_datetime(df['activity_date'])
    competition_start = pd.to_datetime(week_start_date)
    df['days_since_start'] = (df['activity_date'] - competition_start).dt.days
    df['week_num'] = (df['days_since_start'] // 7) + 3
    df['week_label'] = 'Week ' + df['week_num'].astype(int).astype(str)

    # Filter valid weeks
    df = df[(df['days_since_start'] >= 0) & (df['week_num'] >= 3) & (df['week_num'] <= 23)].copy()

    # Only categories that count
    df = df[df['activity_category'].isin(CATEGORIES)].copy()

    # Aggregate
    weekly_data = {}
    for div in DIVISIONS:
        div_df = df[df['athlete_team'] == div]
        weekly_data[div] = {}
        for week in WEEKS:
            week_df = div_df[div_df['week_label'] == week]
            weekly_data[div][week] = {}
            for cat in CATEGORIES:
                cat_df = week_df[week_df['activity_category'] == cat]
                weekly_data[div][week][cat] = {
                    'mileage': round(cat_df['distance_km'].sum(), 1),
                    'points': round(cat_df['points'].sum(), 2),
                }

    return weekly_data


def build_individual_leaderboard(
    activities_df: pd.DataFrame,
    members_df: pd.DataFrame,
    week_start_date: str,
) -> pd.DataFrame:
    """
    Build a per-athlete leaderboard with points breakdown across all 4 categories.

    Returns DataFrame sorted by total_points descending, with columns:
        rank, division, athlete_name, athlete_id,
        run_km, run_pts, walk_km, walk_pts, swim_km, swim_pts, bike_km, bike_pts,
        total_km, total_points, num_activities
    """
    if activities_df.empty:
        return pd.DataFrame()

    df = activities_df.copy()

    # Merge division + athlete_name (from members_df, preferred over activity data)
    df = df.merge(
        members_df[['athlete_id', 'athlete_name', 'athlete_team']].drop_duplicates(),
        on='athlete_id',
        how='left',
        suffixes=('', '_m'),
    )
    if 'athlete_name_m' in df.columns:
        df['athlete_name'] = df['athlete_name_m'].fillna(df.get('athlete_name'))
        df = df.drop(columns=['athlete_name_m'])

    df = df[df['athlete_team'].notna()].copy()
    if df.empty:
        return pd.DataFrame()

    # Numeric + classify
    df['distance'] = pd.to_numeric(df['distance'], errors='coerce').fillna(0)
    df['moving_time'] = pd.to_numeric(df.get('moving_time', 0), errors='coerce').fillna(0)
    df['distance_km'] = df['distance'] / 1000.0
    df['activity_category'] = df.apply(
        lambda row: classify_activity(row['activity_type'], row['distance'], row['moving_time']),
        axis=1,
    )
    df['points'] = df.apply(
        lambda row: calculate_points(row['distance'], row['activity_category']),
        axis=1,
    )

    # Filter to competition period
    df['activity_date'] = pd.to_datetime(df['activity_date'])
    competition_start = pd.to_datetime(week_start_date)
    df = df[df['activity_date'] >= competition_start].copy()

    if df.empty:
        return pd.DataFrame()

    # Pivot per athlete
    def cat_sum(g, cat, col):
        return g[g['activity_category'] == cat][col].sum()

    rows = []
    for (aid, name, team), g in df.groupby(['athlete_id', 'athlete_name', 'athlete_team']):
        rows.append({
            'division': team,
            'athlete_name': name,
            'athlete_id': aid,
            'run_km': round(cat_sum(g, 'run', 'distance_km'), 1),
            'run_pts': round(cat_sum(g, 'run', 'points'), 2),
            'walk_km': round(cat_sum(g, 'walk', 'distance_km'), 1),
            'walk_pts': round(cat_sum(g, 'walk', 'points'), 2),
            'swim_km': round(cat_sum(g, 'swim', 'distance_km'), 1),
            'swim_pts': round(cat_sum(g, 'swim', 'points'), 2),
            'bike_km': round(cat_sum(g, 'bike', 'distance_km'), 1),
            'bike_pts': round(cat_sum(g, 'bike', 'points'), 2),
            'total_km': round(g['distance_km'].sum(), 1),
            'total_points': round(g['points'].sum(), 2),
            'num_activities': len(g),
        })

    lb = pd.DataFrame(rows).sort_values('total_points', ascending=False, ignore_index=True)
    lb.insert(0, 'rank', range(1, len(lb) + 1))
    return lb


def write_sports_challenge_sheet(
    *,
    service,
    sheet_id: str,
    sheet_name: str,
    weekly_data: dict,
    ippt_data: dict | None = None,  # unused, IPPT is manual
) -> None:
    """
    Write weekly data + Sub Total + Mileage Points to the sheet.
    Range: C7 to <end column>29
    """
    _ensure_sheet_exists(service, sheet_id, sheet_name)

    grid = build_weekly_rows(weekly_data=weekly_data)

    range_str = f"'{sheet_name}'!{DATA_START_COL}{FIRST_WEEK_ROW}:{DATA_END_COL}{MILEAGE_POINTS_ROW}"

    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=range_str,
        valueInputOption='USER_ENTERED',
        body={'values': grid},
    ).execute()
