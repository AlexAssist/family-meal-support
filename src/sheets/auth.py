"""SheetsAuth — single OAuth flow for Google Sheets.

All command modules import SheetsAuth from here instead of copying
the _get_sheets_client() dance inline.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from sheets.client import SheetsClient
from shared.errors import SheetSyncError


# Canonical config directory
CONFIG_DIR = Path.home() / ".config" / "family-meal-support"
CREDS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = CONFIG_DIR / "sheets-token.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsAuth:
    """Authenticate to Google Sheets and return a SheetsClient.

    Usage:
        client = SheetsAuth.build()
    """

    @staticmethod
    def build() -> SheetsClient:
        """Authenticate to Google Sheets and return a SheetsClient.

        Raises:
            SheetSyncError: If authentication or client creation fails.
        """
        if not CREDS_PATH.exists():
            raise SheetSyncError("auth", f"credentials.json not found at {CREDS_PATH}")

        creds = None
        if TOKEN_PATH.exists():
            cred_raw = TOKEN_PATH.read_text()
            cred_data = json.loads(cred_raw)
            # Handle double-encoded tokens (bug in some earlier save paths)
            if isinstance(cred_data, str):
                cred_data = json.loads(cred_data)
            from google.oauth2.credentials import Credentials
            creds = Credentials.from_authorized_user_info(cred_data, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
            else:
                from google_auth_oauthlib.flow import InstalledAppFlow
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
                creds = flow.run_local_server(port=0)
            TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_PATH.write_text(json.dumps(creds.to_json()))

        from googleapiclient.discovery import build
        service = build("sheets", "v4", credentials=creds)

        spreadsheet_id = os.environ.get("SHEETS_SPREADSHEET_ID")
        if not spreadsheet_id:
            raise SheetSyncError("auth", "SHEETS_SPREADSHEET_ID environment variable not set")

        return SheetsClient(service, spreadsheet_id)
