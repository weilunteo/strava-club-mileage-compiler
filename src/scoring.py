"""
Scoring Engine for Strava Club Mileage Competition.

Point System:
- Swim: 2km = 1 point (45 min session)
- Run: 10km = 1 point (60 min session)
- Bike: 40km = 1 point (90 min session)

No cap on points - allows catching up.

Division scoring:
- Sum all member points within each division per week
- Weekly Strava mileage = 60% weightage
- IPPT = 40% weightage (managed separately in Google Sheets)
"""

import pandas as pd


# Activity type classification
SWIM_TYPES = ['Swim', 'Open Water Swimming', 'Open Water Swim']
RUN_TYPES = ['Run', 'Trail Run', 'Treadmill', 'Virtual Run', 'Walk', 'Hike', 'Race']
BIKE_TYPES = [
    'Ride',
    'Virtual Ride',
    'E-Bike Ride',
    'Mountain Bike Ride',
    'E-Mountain Bike Ride',
    'Gravel Ride',
    'Indoor Cycling',
]


def classify_activity(activity_type: str) -> str:
    """Classify an activity into swim/run/bike for points calculation."""
    if activity_type in SWIM_TYPES:
        return 'swim'
    elif activity_type in RUN_TYPES:
        return 'run'
    elif activity_type in BIKE_TYPES:
        return 'bike'
    else:
        return 'other'


def calculate_points(
    distance_meters: float,
    activity_category: str,
    swim_km_per_point: float = 2.0,
    run_km_per_point: float = 10.0,
    bike_km_per_point: float = 40.0,
) -> float:
    """
    Calculate points for a given distance and activity category.

    Points formula:
    - Swim: distance_km / 2.0
    - Run: distance_km / 10.0
    - Bike: distance_km / 40.0
    """
    distance_km = distance_meters / 1000.0

    if activity_category == 'swim':
        return distance_km / swim_km_per_point
    elif activity_category == 'run':
        return distance_km / run_km_per_point
    elif activity_category == 'bike':
        return distance_km / bike_km_per_point
    else:
        # For other activities, use run equivalent as default
        return distance_km / run_km_per_point


def calculate_mileage_from_activities(
    activities_df: pd.DataFrame,
    members_df: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """
    Calculate weekly mileage and points per division from individual activities.

    Parameters:
        activities_df: DataFrame with columns [athlete_id, activity_type, distance, activity_date]
        members_df: DataFrame with columns [athlete_id, athlete_name, athlete_team (division)]
        config: dict with scoring parameters

    Returns:
        DataFrame with weekly points per division
    """
    if activities_df.empty:
        return pd.DataFrame()

    swim_km = config.get('swim_km_per_point', 2.0)
    run_km = config.get('run_km_per_point', 10.0)
    bike_km = config.get('bike_km_per_point', 40.0)

    # Merge activities with member division info
    df = activities_df.merge(
        members_df[['athlete_id', 'athlete_team']].drop_duplicates(),
        on='athlete_id',
        how='left',
    )

    # Only include athletes assigned to a division
    df = df[df['athlete_team'].notna()].copy()

    if df.empty:
        return pd.DataFrame()

    # Classify activities and calculate points
    df['activity_category'] = df['activity_type'].apply(classify_activity)
    df['distance'] = pd.to_numeric(df['distance'], errors='coerce').fillna(0)
    df['distance_km'] = df['distance'] / 1000.0
    df['points'] = df.apply(
        lambda row: calculate_points(
            row['distance'],
            row['activity_category'],
            swim_km,
            run_km,
            bike_km,
        ),
        axis=1,
    )

    # Add week number
    df['activity_date'] = pd.to_datetime(df['activity_date'])
    df['week_start'] = df['activity_date'].dt.to_period('W-SUN').apply(lambda r: r.start_time)
    df['week_label'] = 'Week ' + (
        (df['week_start'] - df['week_start'].min()).dt.days // 7 + 1
    ).astype(str)

    # Aggregate by division and week
    weekly_division = (
        df.groupby(['athlete_team', 'week_label', 'week_start'], as_index=False)
        .agg(
            total_distance_km=('distance_km', 'sum'),
            total_points=('points', 'sum'),
            num_activities=('activity_type', 'count'),
        )
        .rename(columns={'athlete_team': 'division'})
        .sort_values(['week_start', 'division'], ignore_index=True)
    )

    return weekly_division


def calculate_mileage_from_leaderboard(
    leaderboard_df: pd.DataFrame,
    members_df: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """
    Calculate weekly mileage and points per division from leaderboard data.

    Note: Leaderboard only provides total distance (no activity type breakdown).
    We use the run conversion rate (10km = 1 point) as default since
    the leaderboard doesn't distinguish activity types.

    For accurate multi-sport scoring, use calculate_mileage_from_activities() instead.
    """
    if leaderboard_df.empty:
        return pd.DataFrame()

    run_km = config.get('run_km_per_point', 10.0)

    # Merge with division info
    df = leaderboard_df.merge(
        members_df[['athlete_id', 'athlete_team']].drop_duplicates(),
        on='athlete_id',
        how='left',
    )

    # Only include athletes assigned to a division
    df = df[df['athlete_team'].notna()].copy()

    if df.empty:
        return pd.DataFrame()

    # Distance is already in meters from the scraper
    df['distance_km'] = pd.to_numeric(df['distance'], errors='coerce').fillna(0) / 1000.0
    df['points'] = df['distance_km'] / run_km

    # Aggregate by division and week
    weekly_division = (
        df.groupby(['athlete_team', 'leaderboard_week', 'leaderboard_date_start'], as_index=False)
        .agg(
            total_distance_km=('distance_km', 'sum'),
            total_points=('points', 'sum'),
            num_athletes=('athlete_id', 'nunique'),
        )
        .rename(columns={'athlete_team': 'division', 'leaderboard_week': 'week_label'})
        .sort_values(['leaderboard_date_start', 'division'], ignore_index=True)
    )

    return weekly_division


def build_division_summary(
    weekly_division_df: pd.DataFrame,
    ippt_data: dict | None = None,
    strava_weightage: float = 0.60,
    ippt_weightage: float = 0.40,
) -> pd.DataFrame:
    """
    Build the final division summary table matching the competition format.

    Parameters:
        weekly_division_df: Output from calculate_mileage_from_activities()
        ippt_data: Optional dict like {'FMD': {'gold': 5, 'silver': 6}, ...}
        strava_weightage: Weight for Strava mileage component (default 0.60)
        ippt_weightage: Weight for IPPT component (default 0.40)

    Returns:
        Summary DataFrame with total points per division
    """
    if weekly_division_df.empty:
        return pd.DataFrame()

    divisions = ['FMD', 'IND', 'EDR', 'BEK', 'VIC']

    # Pivot: divisions as columns, weeks as rows
    pivot = weekly_division_df.pivot_table(
        index='week_label',
        columns='division',
        values=['total_distance_km', 'total_points'],
        aggfunc='sum',
        fill_value=0,
    )

    # Calculate sub-totals per division
    summary = {}
    for div in divisions:
        try:
            total_km = pivot[('total_distance_km', div)].sum()
            total_pts = pivot[('total_points', div)].sum()
        except KeyError:
            total_km = 0.0
            total_pts = 0.0

        summary[div] = {
            'total_mileage_km': round(total_km, 1),
            'strava_sub_points': round(total_pts, 2),
            'strava_weighted': round(total_pts * strava_weightage, 2),
        }

    # Add IPPT if provided
    if ippt_data:
        for div in divisions:
            if div in ippt_data:
                gold = ippt_data[div].get('gold', 0)
                silver = ippt_data[div].get('silver', 0)
                ippt_sub = gold * 3 + silver * 1
                summary[div]['ippt_gold'] = gold
                summary[div]['ippt_silver'] = silver
                summary[div]['ippt_sub_points'] = ippt_sub
                summary[div]['ippt_weighted'] = round(ippt_sub * ippt_weightage, 2)
                summary[div]['total_points'] = round(
                    summary[div]['strava_weighted'] + summary[div]['ippt_weighted'], 2
                )
            else:
                summary[div]['ippt_gold'] = 0
                summary[div]['ippt_silver'] = 0
                summary[div]['ippt_sub_points'] = 0
                summary[div]['ippt_weighted'] = 0.0
                summary[div]['total_points'] = summary[div]['strava_weighted']
    else:
        for div in divisions:
            summary[div]['total_points'] = summary[div]['strava_weighted']

    summary_df = pd.DataFrame(summary).T
    summary_df.index.name = 'division'
    summary_df = summary_df.reset_index()

    return summary_df


def build_individual_leaderboard(
    activities_df: pd.DataFrame,
    members_df: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """
    Build individual athlete leaderboard with points breakdown.

    Returns DataFrame sorted by total points descending.
    """
    if activities_df.empty:
        return pd.DataFrame()

    swim_km = config.get('swim_km_per_point', 2.0)
    run_km = config.get('run_km_per_point', 10.0)
    bike_km = config.get('bike_km_per_point', 40.0)

    # Merge with member info (use suffixes to handle duplicate athlete_name)
    df = activities_df.merge(
        members_df[['athlete_id', 'athlete_name', 'athlete_team']].drop_duplicates(),
        on='athlete_id',
        how='left',
        suffixes=('', '_member'),
    )

    # Prefer athlete_name from activities, fall back to members
    if 'athlete_name_member' in df.columns:
        df['athlete_name'] = df['athlete_name'].fillna(df['athlete_name_member'])
        df = df.drop(columns=['athlete_name_member'])

    df = df[df['athlete_team'].notna()].copy()
    if df.empty:
        return pd.DataFrame()

    df['activity_category'] = df['activity_type'].apply(classify_activity)
    df['distance'] = pd.to_numeric(df['distance'], errors='coerce').fillna(0)
    df['distance_km'] = df['distance'] / 1000.0
    df['points'] = df.apply(
        lambda row: calculate_points(row['distance'], row['activity_category'], swim_km, run_km, bike_km),
        axis=1,
    )

    # Aggregate per athlete
    athlete_summary = (
        df.groupby(['athlete_id', 'athlete_name', 'athlete_team'], as_index=False)
        .agg(
            swim_km=('distance_km', lambda x: x[df.loc[x.index, 'activity_category'] == 'swim'].sum()),
            run_km=('distance_km', lambda x: x[df.loc[x.index, 'activity_category'] == 'run'].sum()),
            bike_km=('distance_km', lambda x: x[df.loc[x.index, 'activity_category'] == 'bike'].sum()),
            total_km=('distance_km', 'sum'),
            total_points=('points', 'sum'),
            num_activities=('activity_type', 'count'),
        )
        .rename(columns={'athlete_team': 'division'})
        .sort_values('total_points', ascending=False, ignore_index=True)
    )

    return athlete_summary
