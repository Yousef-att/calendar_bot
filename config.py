import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class ConfigError(RuntimeError):
    pass


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            f"Missing {name} in .env. Copy .env.example to .env and fill it in."
        )
    return value


class Settings:
    def __init__(self):
        self.telegram_bot_token = _require_env("TELEGRAM_BOT_TOKEN")
        self.openrouter_api_key = _require_env("OPENROUTER_API_KEY")
        self.openrouter_model = os.environ.get("OPENROUTER_MODEL") or "sonnet"

        self.boss_calendar_id = _require_env("BOSS_CALENDAR_ID")
        self.timezone = ZoneInfo(os.environ.get("TIMEZONE") or "Etc/GMT-3")
        self.default_duration_minutes = int(os.environ.get("DEFAULT_DURATION_MINUTES") or "120")

        self.google_token_path = BASE_DIR / (os.environ.get("GOOGLE_TOKEN_PATH") or "token.json")
        self.google_credentials_path = BASE_DIR / (
            os.environ.get("GOOGLE_CREDENTIALS_PATH") or "credentials.json"
        )

        # On a host like Fly.io there's no easy way to mount a local token.json
        # file, so the refresh token can instead be passed as a raw-JSON env
        # var (the exact contents of token.json). If present, write it to disk
        # on every startup so the rest of the code only ever deals with a file.
        token_json = os.environ.get("GOOGLE_TOKEN_JSON")
        if token_json:
            self.google_token_path.write_text(token_json, encoding="utf-8")


def load_settings() -> "Settings":
    return Settings()
