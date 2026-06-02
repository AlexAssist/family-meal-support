#!/usr/bin/env python3
"""One-time OAuth setup for Google Sheets sync.

Run this once in your WSL2 terminal. It opens a browser, gets OAuth consent,
and saves the token to ~/.config/family-meal-support/sheets-token.json.

After this, !sync pull and !sync push work from Discord without any browser.
"""
from __future__ import annotations
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "family-meal-support"
CREDS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = CONFIG_DIR / "sheets-token.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def main():
    if not CREDS_PATH.exists():
        print("ERROR: credentials.json not found at", CREDS_PATH)
        print("Make sure your family-meal-support config is set up.")
        return

    print("Opening browser for Google OAuth consent...")
    print("(If a browser doesn't open, check for a URL printed below)")
    print()

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)

    print("Authenticated! Saving token...")

    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(creds.to_json()))

    print(f"Token saved to {TOKEN_PATH}")
    print()
    print("✅ OAuth setup complete!")
    print("   !sync pull and !sync push will now work from Discord.")


if __name__ == "__main__":
    main()