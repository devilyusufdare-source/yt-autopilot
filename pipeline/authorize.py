"""ONE-TIME setup, run on your own computer (not in the cloud):

    pip install google-auth-oauthlib
    python -m pipeline.authorize client_secret.json

It opens your browser, you sign in with the Google account that owns the YouTube channel and
click Allow. It then prints the three values to paste into GitHub -> Settings -> Secrets:
YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN. Nothing is sent anywhere else.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",   # retention per video (enable "YouTube Analytics API" in the Cloud project first)
]


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    secret_file = Path(argv[0])
    if not secret_file.exists():
        print(f"File not found: {secret_file}\nDownload it from Google Cloud Console -> APIs & Services -> Credentials -> your OAuth client -> Download JSON")
        return 2
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Run:  pip install google-auth-oauthlib")
        return 2

    data = json.loads(secret_file.read_text(encoding="utf-8"))
    key = "installed" if "installed" in data else "web"
    client = data[key]
    flow = InstalledAppFlow.from_client_config(data, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not creds.refresh_token:
        print("No refresh token returned. Remove the app's access at https://myaccount.google.com/permissions and run again.")
        return 1

    print("\nAdd these three secrets to your GitHub repository (Settings -> Secrets and variables -> Actions):\n")
    print(f"YT_CLIENT_ID      = {client['client_id']}")
    print(f"YT_CLIENT_SECRET  = {client['client_secret']}")
    print(f"YT_REFRESH_TOKEN  = {creds.refresh_token}\n")
    print("Keep them private. If the consent screen is still in 'Testing' mode this token expires after 7 days —")
    print("publish the app (OAuth consent screen -> Publish app) so it lasts. See README step 2.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
