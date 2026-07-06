"""
Google Sheets integration for updating/incrementing Strava mileage data.

Requires:
- A Google Cloud service account with Sheets API enabled
- A keys.json file with the service account credentials
- The target Google Sheet shared with the service account email
"""

import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def get_sheets_service(google_api_key_path: str):
    """Create Google Sheets API service instance."""
    credentials = Credentials.from_service_account_file(
        filename=google_api_key_path,
        scopes=['https://www.googleapis.com/auth/spreadsheets'],
    )
    service = build(serviceName='sheets', version='v4', credentials=credentials)
    return service


def _ensure_sheet_exists(service, sheet_id: str, sheet_name: str) -> None:
    """Create a sheet tab if it doesn't already exist."""
    try:
        spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        existing_sheets = [s['properties']['title'] for s in spreadsheet.get('sheets', [])]

        if sheet_name not in existing_sheets:
            body = {
                'requests': [
                    {
                        'addSheet': {
                            'properties': {'title': sheet_name}
                        }
                    }
                ]
            }
            service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body=body).execute()
    except HttpError:
        pass  # If we can't check/create, let the write fail with a clear error


def read_google_sheet(
    *,
    service,
    sheet_id: str,
    sheet_name: str,
) -> pd.DataFrame:
    """Read a Google Sheet tab into a DataFrame."""
    _ensure_sheet_exists(service, sheet_id, sheet_name)

    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=sheet_name)
        .execute()
    )
    values = result.get('values', [])

    if not values or len(values) < 2:
        return pd.DataFrame()

    df = pd.DataFrame(data=values[1:], columns=values[0], dtype='str')
    df = df.replace(r'^\s*$', None, regex=True)

    return df


def write_google_sheet(
    *,
    service,
    sheet_id: str,
    sheet_name: str,
    df: pd.DataFrame,
    clear_first: bool = True,
) -> None:
    """Write a DataFrame to a Google Sheet tab (overwrites existing data)."""
    _ensure_sheet_exists(service, sheet_id, sheet_name)

    # Fill NaN with empty string for Sheets
    df_out = df.fillna('')

    # Convert all values to strings to avoid serialization issues
    df_out = df_out.astype(str).replace('nan', '')

    # Convert to list format
    data = [df_out.columns.tolist()]
    data.extend(df_out.values.tolist())

    if clear_first:
        service.spreadsheets().values().clear(
            spreadsheetId=sheet_id, range=sheet_name, body={}
        ).execute()

    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=sheet_name,
        valueInputOption='USER_ENTERED',
        body={'values': data},
    ).execute()


def update_google_sheet_incremental(
    *,
    service,
    sheet_id: str,
    sheet_name: str,
    df_new: pd.DataFrame,
    key_columns: list[str],
) -> pd.DataFrame:
    """
    Incrementally update a Google Sheet - adds new rows, updates existing ones.

    Parameters:
        service: Google Sheets API service
        sheet_id: Google Sheet file ID
        sheet_name: Tab/sheet name
        df_new: New data to upsert
        key_columns: Columns to use as unique key for matching existing rows

    Returns:
        The merged DataFrame that was written
    """
    _ensure_sheet_exists(service, sheet_id, sheet_name)

    # Read existing data
    df_existing = read_google_sheet(service=service, sheet_id=sheet_id, sheet_name=sheet_name)

    if df_existing.empty:
        # First time - just write
        write_google_sheet(service=service, sheet_id=sheet_id, sheet_name=sheet_name, df=df_new)
        return df_new

    # Remove existing rows that match new data keys (will be replaced)
    merge_indicator = df_existing.merge(
        df_new[key_columns].drop_duplicates(),
        on=key_columns,
        how='outer',
        indicator=True,
    )
    df_keep = merge_indicator[merge_indicator['_merge'] == 'left_only'].drop(columns=['_merge'])
    df_keep = df_keep[df_existing.columns]

    # Combine: keep old non-overlapping + all new
    df_merged = pd.concat([df_new, df_keep], axis=0, ignore_index=True, sort=False)

    # Write back
    write_google_sheet(service=service, sheet_id=sheet_id, sheet_name=sheet_name, df=df_merged)

    return df_merged


def update_execution_time(
    *,
    service,
    sheet_id: str,
    sheet_name: str,
    timezone: str = 'UTC',
) -> None:
    """Write the current execution timestamp to a sheet."""
    _ensure_sheet_exists(service, sheet_id, sheet_name)

    now = str(pd.Timestamp.now(tz=timezone).replace(microsecond=0, tzinfo=None))

    service.spreadsheets().values().clear(
        spreadsheetId=sheet_id, range=sheet_name, body={}
    ).execute()

    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=sheet_name,
        valueInputOption='USER_ENTERED',
        body={'values': [['last_execution'], [now]]},
    ).execute()
