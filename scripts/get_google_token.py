#!/usr/bin/env python3
"""
Generate a new Google OAuth refresh token for GitHub Actions.
Run locally and paste the printed refresh_token into GitHub Secrets as GOOGLE_REFRESH_TOKEN.
"""
import os
import sys


def main():
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        print("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars first.")
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Installing google-auth-oauthlib...")
        os.system(f"{sys.executable} -m pip install google-auth-oauthlib")
        from google_auth_oauthlib.flow import InstalledAppFlow

    # Same scope used by sheets.py
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            }
        },
        SCOPES,
    )

    creds = flow.run_local_server(port=0)
    print("\n=== NEW REFRESH TOKEN ===")
    print(creds.refresh_token)
    print("=========================\n")
    print("Copy the token above into GitHub Secrets as GOOGLE_REFRESH_TOKEN")


if __name__ == "__main__":
    main()
