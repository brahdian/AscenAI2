"""Google Sheets integration handlers."""
from __future__ import annotations

import httpx

GOOGLE_SHEETS_READ_SCHEMA = {
    "type": "object",
    "required": ["range"],
    "properties": {
        "range": {
            "type": "string",
            "description": "A1 notation range, e.g. Sheet1!A1:D10 or Sheet1!A:A",
        },
        "major_dimension": {
            "type": "string",
            "description": "ROWS or COLUMNS",
            "default": "ROWS",
        },
    },
}

GOOGLE_SHEETS_APPEND_SCHEMA = {
    "type": "object",
    "required": ["range", "values"],
    "properties": {
        "range": {
            "type": "string",
            "description": "Sheet name or range to append to, e.g. Sheet1",
        },
        "values": {
            "type": "array",
            "items": {"type": "array"},
            "description": "2D array of values to append, e.g. [['Name', 'Email', 'Date']]",
        },
    },
}

_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


async def handle_google_sheets_read(parameters: dict, tenant_config: dict) -> dict:
    """Read rows from a Google Sheet."""
    access_token = tenant_config.get("access_token", "")
    spreadsheet_id = tenant_config.get("spreadsheet_id", "")

    if not access_token or not spreadsheet_id:
        return {"error": "Google Sheets not configured. Add your access token and spreadsheet ID."}

    sheet_range = parameters["range"]
    major_dim = parameters.get("major_dimension", "ROWS")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_BASE}/{spreadsheet_id}/values/{sheet_range}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"majorDimension": major_dim},
        )

    if resp.status_code == 401:
        return {"error": "Google Sheets token expired. Please reconnect your Google account."}
    if not resp.is_success:
        return {"error": f"Google Sheets API error: {resp.status_code}"}

    data = resp.json()
    rows = data.get("values", [])
    return {
        "range": data.get("range"),
        "rows": rows,
        "row_count": len(rows),
    }


async def handle_google_sheets_append(parameters: dict, tenant_config: dict) -> dict:
    """Append rows to a Google Sheet."""
    access_token = tenant_config.get("access_token", "")
    spreadsheet_id = tenant_config.get("spreadsheet_id", "")

    if not access_token or not spreadsheet_id:
        return {"error": "Google Sheets not configured. Add your access token and spreadsheet ID."}

    sheet_range = parameters["range"]
    values = parameters["values"]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_BASE}/{spreadsheet_id}/values/{sheet_range}:append",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
            json={"values": values},
        )

    if resp.status_code == 401:
        return {"error": "Google Sheets token expired. Please reconnect your Google account."}
    if not resp.is_success:
        return {"error": f"Google Sheets API error: {resp.status_code}"}

    result = resp.json().get("updates", {})
    return {
        "updated_range": result.get("updatedRange"),
        "rows_appended": result.get("updatedRows", len(values)),
        "success": True,
    }
