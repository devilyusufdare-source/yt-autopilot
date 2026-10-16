"""ONE-TIME Facebook setup, run on your own computer:

    python facebook_setup.py APP_ID APP_SECRET SHORT_LIVED_USER_TOKEN

Turns the short-lived token from the Graph API Explorer into a PERMANENT Page key and prints the
two values to paste into GitHub -> Settings -> Secrets -> Actions: FB_PAGE_ID and FB_PAGE_TOKEN.
Nothing is sent anywhere except to Facebook's own API (graph.facebook.com).
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

GRAPH = "https://graph.facebook.com/v21.0"


def _get(path: str, params: dict) -> dict:
    url = f"{GRAPH}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(body).get("error", {}).get("message", body)
        except Exception:  # noqa: BLE001
            msg = body
        raise SystemExit(f"Facebook answered HTTP {e.code}: {msg}") from None


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    app_id, app_secret, short_token = (a.strip() for a in argv)

    print("1/3 asking Facebook for a long-lived token...")
    long_user = _get("oauth/access_token", {
        "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": app_secret,
        "fb_exchange_token": short_token,
    })["access_token"]

    print("2/3 reading the Pages this account manages...")
    pages = _get("me/accounts", {"access_token": long_user, "fields": "id,name,access_token,tasks"}).get("data", [])
    if not pages:
        raise SystemExit("No Pages found. Make sure you selected the Page in the Facebook window when generating the token "
                         "(Generate Access Token -> choose the Page), and that pages_show_list was ticked.")
    if len(pages) > 1:
        print("   Pages found:")
        for i, p in enumerate(pages, 1):
            print(f"   {i}. {p['name']} (id {p['id']})")
        choice = input("   Which number is the channel's Page? ").strip()
        page = pages[int(choice) - 1]
    else:
        page = pages[0]

    print("3/3 checking the Page key...")
    info = _get("debug_token", {"input_token": page["access_token"], "access_token": f"{app_id}|{app_secret}"}).get("data", {})
    expires = info.get("expires_at", 0)
    scopes = info.get("scopes", [])
    missing = [s for s in ("pages_manage_posts", "pages_read_engagement", "publish_video") if s not in scopes]

    print()
    print("=" * 70)
    print(f"Page: {page['name']}")
    print(f"FB_PAGE_ID    = {page['id']}")
    print(f"FB_PAGE_TOKEN = {page['access_token']}")
    print("=" * 70)
    print("Key expiry:", "never (good)" if not expires else f"expires_at={expires} (not permanent - tell Claude)")
    if missing:
        print("WARNING: these permissions are missing:", ", ".join(missing), "- regenerate the token with them ticked.")
    print("\nPaste the two values into GitHub -> Settings -> Secrets and variables -> Actions -> New repository secret.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
