"""
Scoring Engine for Strava Club Mileage Competition.

Point System (per km):
- Run (pace < 9 min/km): 0.1 pt/km  (10 km = 1 pt)
- Walk (pace >= 9 min/km): 0.05 pt/km  (20 km = 1 pt)
- Swim: 0.5 pt/km  (2 km = 1 pt)
- Bike: 0.025 pt/km  (40 km = 1 pt)

Pace-based classification: If a Run/Walk/Hike activity has moving pace
>= 9 min/km, it's counted as Walk. Otherwise counted as Run.
"""

import pandas as pd


# Activity type classification (from Strava's activity_type field)
SWIM_TYPES = ['Swim', 'Open Water Swimming', 'Open Water Swim']
RUN_LIKE_TYPES = ['Run', 'Trail Run', 'Treadmill', 'Virtual Run', 'Walk', 'Hike', 'Race']
BIKE_TYPES = [
    'Ride',
    'Virtual Ride',
    'E-Bike Ride',
    'Mountain Bike Ride',
    'E-Mountain Bike Ride',
    'Gravel Ride',
    'Indoor Cycling',
]

# Points per km for each category
POINTS_PER_KM = {
    'run': 0.10,
    'walk': 0.05,
    'swim': 0.50,
    'bike': 0.025,
}

# Pace threshold: if pace >= this many min/km, classify as walk
WALK_PACE_THRESHOLD_MIN_PER_KM = 9.0


def compute_pace_min_per_km(distance_m: float, moving_time_s: float) -> float | None:
    """Compute pace in min/km. Returns None if distance or time is zero/invalid."""
    if not distance_m or not moving_time_s or distance_m <= 0 or moving_time_s <= 0:
        return None
    return (moving_time_s / 60.0) / (distance_m / 1000.0)


def classify_activity(activity_type: str, distance_m: float = 0, moving_time_s: float = 0) -> str:
    """
    Classify an activity into run/walk/swim/bike/other.

    For run-like activities, uses pace to decide run vs walk:
    - pace < 9 min/km => run
    - pace >= 9 min/km => walk
    - If pace can't be computed and type is 'Walk' or 'Hike' => walk
    - Otherwise default to run
    """
    if activity_type in SWIM_TYPES:
        return 'swim'
    if activity_type in BIKE_TYPES:
        return 'bike'
    if activity_type in RUN_LIKE_TYPES:
        pace = compute_pace_min_per_km(distance_m, moving_time_s)
        if pace is not None:
            return 'walk' if pace >= WALK_PACE_THRESHOLD_MIN_PER_KM else 'run'
        # Fallback: use activity type name
        if activity_type in ('Walk', 'Hike'):
            return 'walk'
        return 'run'
    return 'other'


def calculate_points(distance_m: float, category: str) -> float:
    """Calculate points for a given distance (meters) and category."""
    distance_km = distance_m / 1000.0
    return distance_km * POINTS_PER_KM.get(category, 0)
