"""
Strava Club Scraper - adapted from https://github.com/roboes/strava-club-scraper
Scrapes leaderboard and activity data from a Strava Club using Selenium.
"""

import re
import time
from datetime import timedelta
from io import StringIO
from typing import Any

import lxml.html as lh
import pandas as pd
from dateutil import parser, relativedelta
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .selenium_utils import selenium_webdriver


# Global driver reference
_driver = None


def get_driver(headless: bool = False):
    """Get or create the Selenium WebDriver instance."""
    global _driver
    if _driver is None or not _driver.service.is_connectable():
        _driver = selenium_webdriver(headless=headless)
    return _driver


def quit_driver():
    """Quit the Selenium WebDriver."""
    global _driver
    if _driver is not None:
        _driver.quit()
        _driver = None


def strava_authentication(
    *,
    strava_login: str | None = None,
    strava_password: str | None = None,
    headless: bool = False,
    login_mode: str = 'user',
):
    """
    Authenticate to Strava.

    login_mode:
        'credentials' - auto-login with email/password (may fail due to 2FA)
        'user' - opens browser and waits for manual login (recommended)
    """
    driver = get_driver(headless=headless)

    driver.get(url='https://www.strava.com/login')
    time.sleep(3)

    # Wait for email field to appear
    try:
        if driver.find_element(by=By.ID, value='desktop-email'):
            pass
    except NoSuchElementException:
        while True:
            try:
                driver.find_element(by=By.ID, value='desktop-email')
                break
            except NoSuchElementException:
                time.sleep(2)

    # Reject cookies
    try:
        driver.find_element(by=By.XPATH, value='.//button[@data-cy="deny-cookies"]').click()
    except NoSuchElementException:
        pass

    if login_mode == 'credentials' and strava_login and strava_password:
        # Auto-login
        field_login = next(
            element
            for element in driver.find_elements(by=By.XPATH, value='.//*[@data-cy="email"]')
            if element.is_displayed()
        )
        field_login.send_keys(strava_login)
        time.sleep(2)
        field_login.send_keys(Keys.ENTER)
        time.sleep(2)

        # Password
        next(
            element
            for element in driver.find_elements(
                by=By.XPATH, value='.//button[text()="Use password instead"]'
            )
            if element.is_displayed()
        ).click()

        field_password = next(
            element
            for element in driver.find_elements(by=By.XPATH, value='.//*[@data-cy="password"]')
            if element.is_displayed()
        )
        field_password.send_keys(strava_password)
        time.sleep(2)
        field_password.send_keys(Keys.ENTER)
    else:
        # Wait for user to manually log in
        print("Please log in to Strava in the browser window...")
        print("Waiting for dashboard to load (timeout: 5 minutes)...")
        WebDriverWait(driver=driver, timeout=300).until(
            method=EC.url_contains(url='https://www.strava.com/dashboard')
        )
        print("Login successful!")

    time.sleep(3)
    return driver


def strava_club_leaderboard(
    *,
    club_ids: list[str],
    filter_date_min: str,
    filter_date_max: str,
    timezone: str = 'UTC',
) -> pd.DataFrame:
    """
    Scrape leaderboard data from one or multiple Strava Club(s).

    Returns DataFrame with columns:
        club_id, leaderboard_week, leaderboard_date_start, leaderboard_date_end,
        rank, athlete_id, athlete_name, activities, moving_time, distance,
        distance_longest, average_speed, pace, elevation_gain
    """
    filter_date_min_dt = parser.parse(filter_date_min)
    filter_date_max_dt = parser.parse(filter_date_max)

    driver = get_driver()
    club_leaderboard_df = pd.DataFrame(data=None, index=None, dtype='str')

    for club_id in club_ids:
        # Open Strava Club leaderboard page
        driver.get(url=f'https://www.strava.com/clubs/{club_id}/leaderboard')
        time.sleep(3)

        # Get club metadata
        try:
            club_name = driver.find_element(
                by=By.XPATH, value='//h1[@class="mb-sm"]'
            ).text.split(sep='\n')[0]
        except NoSuchElementException:
            club_name = f"Club {club_id}"

        try:
            club_activity_type = driver.find_element(
                by=By.XPATH,
                value='//div[@class="club-meta"]//div[@class="location"]//span[@class="app-icon-wrapper  "]',
            ).text
        except NoSuchElementException:
            club_activity_type = 'Multisport'

        try:
            club_location = driver.find_element(
                by=By.XPATH, value='//div[@class="club-meta"]//div[@class="location"]'
            ).text
            club_location = re.sub(
                pattern=rf'^{re.escape(club_activity_type)}(.*)$',
                repl=r'\1',
                string=club_location,
                flags=0,
            ).strip()
        except NoSuchElementException:
            club_location = ''

        # --- Current week leaderboard ---
        club_leaderboard_import_df = _scrape_leaderboard_table(
            driver=driver,
            club_id=club_id,
            club_name=club_name,
            club_activity_type=club_activity_type,
            club_location=club_location,
            week_offset=0,
            timezone=timezone,
        )

        if club_leaderboard_import_df is not None:
            club_leaderboard_df = pd.concat(
                objs=[club_leaderboard_df, club_leaderboard_import_df],
                axis=0,
                ignore_index=True,
                sort=False,
            )

        # --- Previous week leaderboard ---
        try:
            driver.find_element(by=By.XPATH, value='//span[@class="button last-week"]').click()
            time.sleep(2)
        except NoSuchElementException:
            continue

        club_leaderboard_prev_df = _scrape_leaderboard_table(
            driver=driver,
            club_id=club_id,
            club_name=club_name,
            club_activity_type=club_activity_type,
            club_location=club_location,
            week_offset=-1,
            timezone=timezone,
        )

        if club_leaderboard_prev_df is not None:
            club_leaderboard_df = pd.concat(
                objs=[club_leaderboard_df, club_leaderboard_prev_df],
                axis=0,
                ignore_index=True,
                sort=False,
            )

    if club_leaderboard_df.empty:
        return club_leaderboard_df

    # Standardize column names
    club_leaderboard_df = club_leaderboard_df.rename(
        columns={
            'athlete': 'athlete_name',
            'time': 'moving_time',
            'elev_gain': 'elevation_gain',
            'rides': 'activities',
            'runs': 'activities',
            'longest': 'distance_longest',
            'avg_speed': 'average_speed',
            'avg_pace': 'pace',
        }
    )

    # Create leaderboard_week label
    if 'leaderboard_date_start' in club_leaderboard_df.columns:
        club_leaderboard_df['leaderboard_week'] = (
            club_leaderboard_df['leaderboard_date_start'].dt.strftime('%Y-%m-%d')
            + ' to '
            + club_leaderboard_df['leaderboard_date_end'].dt.strftime('%Y-%m-%d')
        )

    # Convert distance from "X km" to meters (float)
    if 'distance' in club_leaderboard_df.columns:
        club_leaderboard_df['distance'] = (
            club_leaderboard_df['distance']
            .astype(str)
            .str.replace(r'^--$', '0 km', regex=True)
            .str.replace(',', '', regex=True)
            .str.replace(r' km$', '', regex=True)
            .astype(float)
            * 1000  # Convert km to meters
        )

    # Convert moving_time from "Xh Ym" to seconds
    if 'moving_time' in club_leaderboard_df.columns:
        club_leaderboard_df['moving_time'] = (
            club_leaderboard_df['moving_time']
            .fillna('0m')
            .str.replace(r'^([0-9]+m)$', r'00:\1', regex=True)
            .str.replace(r'h ', ':', regex=True)
            .str.replace(r'm$', '', regex=True)
            .apply(lambda row: float(row.split(':')[0]) * 3600 + float(row.split(':')[1]) * 60)
        )

    # Convert elevation_gain
    if 'elevation_gain' in club_leaderboard_df.columns:
        club_leaderboard_df['elevation_gain'] = (
            club_leaderboard_df['elevation_gain']
            .astype(str)
            .str.replace(r'^--$', '0 m', regex=True)
            .str.replace(',', '', regex=True)
            .str.replace(r' m$', '', regex=True)
            .astype(float)
        )

    # Filter date range
    club_leaderboard_df = club_leaderboard_df.query(
        'leaderboard_date_start >= @filter_date_min_dt & leaderboard_date_end <= @filter_date_max_dt'
    ).reset_index(drop=True)

    # Sort
    club_leaderboard_df = club_leaderboard_df.sort_values(
        by=['club_id', 'leaderboard_date_start', 'rank'], ignore_index=True
    )

    return club_leaderboard_df


def _scrape_leaderboard_table(
    *,
    driver,
    club_id: str,
    club_name: str,
    club_activity_type: str,
    club_location: str,
    week_offset: int,
    timezone: str,
) -> pd.DataFrame | None:
    """Scrape a single leaderboard table (current or previous week)."""
    try:
        driver.find_element(
            by=By.XPATH, value='//div[@class="leaderboard"]//h4[@class="empty-results"]'
        )
        return None
    except NoSuchElementException:
        pass

    try:
        leaderboard_html = driver.find_element(
            by=By.XPATH, value='//table[@class="dense striped sortable"]'
        ).get_attribute('outerHTML')
    except NoSuchElementException:
        return None

    leaderboard_dfs = pd.read_html(io=StringIO(leaderboard_html), flavor='lxml', encoding='utf-8')

    if not leaderboard_dfs or leaderboard_dfs[0].empty:
        return None

    df = leaderboard_dfs[0]

    # Calculate week dates
    now = pd.Timestamp.now(tz=timezone).replace(tzinfo=None).floor('d').to_pydatetime()

    if week_offset == 0:
        date_start = now + relativedelta.relativedelta(weekday=relativedelta.MO(-1))
        date_end = date_start + relativedelta.relativedelta(weekday=relativedelta.SU(+1))
    else:
        date_start = now + relativedelta.relativedelta(weekday=relativedelta.MO(-2))
        date_end = date_start + relativedelta.relativedelta(weekday=relativedelta.SU(+1))

    df['leaderboard_date_start'] = date_start
    df['leaderboard_date_end'] = date_end
    df['club_id'] = club_id
    df['club_name'] = club_name
    df['club_activity_type'] = club_activity_type
    df['club_location'] = club_location

    # Extract athlete_ids from links
    try:
        hrefs = lh.fromstring(html=leaderboard_html).xpath('.//tr//td//div//a//@href')
        athlete_ids = [re.sub(r'^.*/athletes/([0-9]+).*$', r'\1', h) for h in hrefs if '/athletes/' in h]
        if len(athlete_ids) == len(df):
            df['athlete_id'] = athlete_ids
        else:
            df['athlete_id'] = None
    except Exception:
        df['athlete_id'] = None

    # Lowercase column names
    df.columns = [c.lower().replace(' ', '_') for c in df.columns]

    return df


def strava_club_activities(
    *,
    club_ids: list[str],
    filter_activities_type: list[str] | None = None,
    filter_date_min: str,
    filter_date_max: str,
    timezone: str = 'UTC',
) -> pd.DataFrame:
    """
    Scrape individual activities from Strava Club feed.

    Returns DataFrame with activity details including:
        activity_type, distance (meters), moving_time (seconds), athlete_id, athlete_name, etc.
    """
    filter_date_min_dt = parser.parse(filter_date_min)
    filter_date_max_dt = parser.parse(filter_date_max)

    driver = get_driver()
    data = []

    for club_id in club_ids:
        # Open club feed
        driver.get(
            url=f'https://www.strava.com/dashboard?club_id={club_id}&feed_type=club&num_entries=100'
        )
        time.sleep(3)

        # Scroll to load activities
        scroll_attempts = 0
        max_scrolls = 50

        while scroll_attempts < max_scrolls:
            try:
                driver.find_element(
                    by=By.XPATH, value='//div[text()="No more recent activity available."]'
                )
                break
            except NoSuchElementException:
                activities = driver.find_elements(
                    by=By.XPATH, value='//div[@data-testid="activity_entry_container"]'
                )
                if not activities:
                    break

                # Check date of last activity
                try:
                    activity_date_text = activities[-1].find_element(
                        by=By.XPATH, value='.//..//..//..//..//..//time'
                    ).text
                    activity_date_text = _normalize_date_text(activity_date_text, timezone)
                    activity_date = parser.parse(activity_date_text)

                    if activity_date < filter_date_min_dt:
                        break
                except Exception:
                    pass

                # Scroll down
                driver.execute_script(
                    'arguments[0].scrollIntoView({block: "start"});',
                    driver.find_elements(by=By.XPATH, value='//*[@data-testid="web-feed-entry"]')[
                        -1
                    ],
                )
                time.sleep(4)
                scroll_attempts += 1

        # Collect activity IDs
        activities_id = []
        feed_entries = driver.find_elements(
            by=By.XPATH, value='//div[@data-testid="web-feed-entry"]'
        )

        for entry in feed_entries:
            try:
                date_text = entry.find_element(
                    by=By.XPATH, value='.//time[@data-testid="date_at_time"]'
                ).text
                date_text = _normalize_date_text(date_text, timezone)
                entry_date = parser.parse(date_text)

                if filter_date_min_dt <= entry_date < (filter_date_max_dt + timedelta(days=1)):
                    links = entry.find_elements(
                        by=By.XPATH,
                        value='.//div[@data-testid="activity_entry_container"]//h3//a',
                    )
                    for link in links:
                        href = link.get_attribute('href')
                        act_id = re.sub(r'^.*/activities/(.*)$', r'\1', href)
                        act_id = re.sub(r'^([0-9]+)(\?|/|#).*$', r'\1', act_id)
                        activities_id.append(act_id)
            except Exception:
                continue

        activities_id = list(set(activities_id))

        # Scrape each activity
        for activity_id in activities_id:
            d = _scrape_single_activity(driver, activity_id, club_id, timezone)
            if d is not None:
                data.append(d)

    if not data:
        return pd.DataFrame()

    club_activities_df = pd.DataFrame(data=data)

    # Filter activity types
    if filter_activities_type:
        club_activities_df = club_activities_df.query(
            'activity_type.isin(@filter_activities_type)'
        ).reset_index(drop=True)

    # Filter date range
    if not club_activities_df.empty:
        club_activities_df = club_activities_df.query(
            'activity_date >= @filter_date_min_dt & activity_date <= @filter_date_max_dt'
        ).reset_index(drop=True)

    return club_activities_df


def _scrape_single_activity(driver, activity_id: str, club_id: str, timezone: str) -> dict | None:
    """Scrape a single activity page for details."""
    driver.get(url=f'https://www.strava.com/activities/{activity_id}/overview')
    time.sleep(2)

    try:
        driver.find_element(by=By.XPATH, value='//pre[text()="Too Many Requests"]')
        print(f"Rate limited! Stopping at activity {activity_id}")
        return None
    except NoSuchElementException:
        pass

    d = {'club_id': club_id, 'activity_id': activity_id}

    try:
        title_parts = driver.find_element(
            by=By.XPATH, value='.//span[@class="title"]'
        ).text.split(' – ')
        d['athlete_name'] = title_parts[0] if len(title_parts) > 0 else ''
        d['activity_type'] = title_parts[1] if len(title_parts) > 1 else ''
    except Exception:
        return None

    # Activity date
    try:
        date_text = driver.find_element(
            by=By.XPATH, value='.//div[@class="details-container"]//time'
        ).text
        date_text = re.sub(r'^(.*) on (.*)$', r'\2 \1', date_text)
        d['activity_date'] = parser.parse(date_text)
    except Exception:
        d['activity_date'] = None

    # Athlete ID
    try:
        athlete_href = driver.find_element(
            by=By.XPATH, value='.//div[@class="details-container"]//a'
        ).get_attribute('href')
        d['athlete_id'] = re.sub(r'^.*/athletes/(.*)$', r'\1', athlete_href)
    except Exception:
        d['athlete_id'] = None

    # Distance
    try:
        inline_stats = driver.find_element(
            by=By.XPATH, value='.//ul[@class="inline-stats section"]'
        ).text.split('\n')

        stats_dict = dict(zip(inline_stats[1::2], inline_stats[0::2]))

        if 'Distance' in stats_dict:
            dist = stats_dict['Distance']
            dist = re.sub(r',', '', dist)
            dist = re.sub(r'\s*km$', '', dist)
            dist = re.sub(r'\s*m$', '', dist)  # For Swim distances in meters
            d['distance'] = float(dist) * 1000  # Convert km to meters
        elif any('km' in v for v in inline_stats):
            for val in inline_stats:
                if 'km' in val:
                    dist = re.sub(r',', '', val)
                    dist = re.sub(r'\s*km$', '', dist)
                    d['distance'] = float(dist) * 1000
                    break

        if 'Moving Time' in stats_dict:
            d['moving_time_str'] = stats_dict['Moving Time']
        elif 'Elapsed Time' in stats_dict:
            d['moving_time_str'] = stats_dict['Elapsed Time']

    except Exception:
        pass

    # Parse moving time to seconds
    if 'moving_time_str' in d:
        try:
            time_str = d['moving_time_str']
            parts = time_str.split(':')
            if len(parts) == 3:
                d['moving_time'] = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                d['moving_time'] = int(parts[0]) * 60 + int(parts[1])
            del d['moving_time_str']
        except Exception:
            if 'moving_time_str' in d:
                del d['moving_time_str']

    return d


def strava_club_members(
    *,
    club_ids: list[str],
    club_members_teams: dict[str, list[str]] | None = None,
    timezone: str = 'UTC',
) -> pd.DataFrame:
    """Scrape club members list."""
    driver = get_driver()
    data = []

    for club_id in club_ids:
        driver.get(url=f'https://www.strava.com/clubs/{club_id}/members')
        time.sleep(3)

        try:
            club_name = driver.find_element(
                by=By.XPATH, value='//h1[@class="mb-sm"]'
            ).text.split('\n')[0]
        except NoSuchElementException:
            club_name = f"Club {club_id}"

        # Paginate through members
        while True:
            try:
                members = driver.find_elements(
                    by=By.XPATH, value='//ul[@class="list-athletes"]//li'
                )

                for member in members:
                    d = {'club_id': club_id, 'club_name': club_name}

                    try:
                        athlete_link = member.find_element(
                            by=By.XPATH, value='.//div[@class="text-headline"]//a'
                        ).get_attribute('href')
                        d['athlete_id'] = re.sub(r'^.*/athletes/(.*)$', r'\1', athlete_link)
                    except Exception:
                        d['athlete_id'] = None

                    try:
                        d['athlete_name'] = member.find_element(
                            by=By.XPATH, value='.//div[@class="text-headline"]'
                        ).text
                    except Exception:
                        d['athlete_name'] = ''

                    data.append(d)

                # Try next page
                driver.find_element(by=By.XPATH, value='.//li[@class="next_page"]').click()
                time.sleep(2)
            except NoSuchElementException:
                break

    club_members_df = pd.DataFrame(data=data).drop_duplicates(ignore_index=True)

    # Add team/division assignments
    if club_members_teams:
        team_records = []
        for team_name, athlete_ids in club_members_teams.items():
            for aid in athlete_ids:
                team_records.append({'athlete_id': str(aid).strip(), 'athlete_team': team_name})

        teams_df = pd.DataFrame(team_records)

        # Group multiple team assignments
        teams_df = (
            teams_df.groupby('athlete_id', as_index=False)
            .agg(athlete_team=('athlete_team', ', '.join))
        )

        club_members_df = club_members_df.merge(teams_df, on='athlete_id', how='left')
    else:
        club_members_df['athlete_team'] = None

    return club_members_df


def _normalize_date_text(date_text: str, timezone: str) -> str:
    """Normalize 'Today at...' and 'Yesterday at...' to actual dates."""
    today = str(pd.Timestamp.now(tz=timezone).date())
    yesterday = str(pd.Timestamp.now(tz=timezone).date() - timedelta(days=1))

    date_text = re.sub(r'^(Today at |Today)(.*)', rf'{today} \2', date_text)
    date_text = re.sub(r'^(Yesterday at |Yesterday)(.*)', rf'{yesterday} \2', date_text)

    return date_text
