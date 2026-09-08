"""
Run this ONCE, interactively, on your own machine to authorize the bot to
manage events on your Google Calendar (including your boss's calendar, once
he's shared it with your account with edit permission).

Prerequisites:
  1. A Google Cloud project with the Calendar API enabled.
  2. An OAuth client of type "Desktop app", downloaded as credentials.json
     into this folder (see README.md for the exact steps).

This opens a browser window for you to log in and approve access, then saves
a refresh token to token.json. That file grants edit access to your Google
Calendar -- treat it like a password: never share it, never commit it.

For deployment, either copy token.json alongside bot.py, or set its exact
contents as the GOOGLE_TOKEN_JSON environment variable (see .env.example).
"""

import os

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

from calendar_client import SCOPES
from config import BASE_DIR

# Only the two Google-related paths are needed here, so we read them directly
# instead of calling config.load_settings() (which also requires the bot's
# other, unrelated settings like TELEGRAM_BOT_TOKEN to be filled in already).
load_dotenv(BASE_DIR / ".env")


def main():
    credentials_path = BASE_DIR / os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    token_path = BASE_DIR / os.environ.get("GOOGLE_TOKEN_PATH", "token.json")

    if not credentials_path.exists():
        raise SystemExit(
            f"Missing {credentials_path}. Download your OAuth client's credentials.json "
            "there first (see README.md)."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"Saved refresh token to {token_path}.")
    print("You can now run bot.py. For cloud deployment, see README.md for how to")
    print("pass this file's contents as the GOOGLE_TOKEN_JSON secret instead.")


if __name__ == "__main__":
    main()
