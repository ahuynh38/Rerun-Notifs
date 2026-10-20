"""File locations and user settings for the YouTube notifier.

Everything the app reads or writes lives in %APPDATA%\\YouTubeNotifier\\,
so secrets (webhook URL, OAuth tokens) never end up in the project folder.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path(os.environ["APPDATA"]) / "YouTubeNotifier"

CONFIG_FILE = APP_DIR / "config.json"
CLIENT_SECRET_FILE = APP_DIR / "client_secret.json"
TOKEN_FILE = APP_DIR / "token.json"
STATE_FILE = APP_DIR / "state.json"
LOG_FILE = APP_DIR / "notifier.log"
LOCK_FILE = APP_DIR / "notifier.lock"

DEFAULTS = {
    "webhook_url": "",
    # Optional: where "needs attention" alerts go. Empty means use webhook_url.
    "alert_webhook_url": "",
    "message": "Hey gamers. New rerun just dropped",
    "poll_interval_seconds": 300,
}

# Discord still accepts webhooks on its old discordapp.com domain.
WEBHOOK_PREFIXES = (
    "https://discord.com/api/webhooks/",
    "https://discordapp.com/api/webhooks/",
)


class ConfigError(Exception):
    """Raised when config.json is missing or incomplete."""


@dataclass(frozen=True)
class Config:
    webhook_url: str
    alert_webhook_url: str
    message: str
    poll_interval_seconds: int


def load_config() -> Config:
    """Read config.json, creating a template on first use."""
    APP_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULTS, indent=2), encoding="utf-8")
        raise ConfigError(f"Created {CONFIG_FILE}. Add your Discord webhook URL to it.")

    try:
        loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{CONFIG_FILE} is not valid JSON: {e}") from e
    if not isinstance(loaded, dict):
        raise ConfigError(f"{CONFIG_FILE} must contain a JSON object ({{...}}).")
    data = {**DEFAULTS, **loaded}

    webhook_url = data["webhook_url"]
    if not isinstance(webhook_url, str) or not webhook_url.startswith(WEBHOOK_PREFIXES):
        raise ConfigError(f"Set a valid Discord webhook URL in {CONFIG_FILE}.")

    alert_webhook_url = data["alert_webhook_url"] or webhook_url
    if not isinstance(alert_webhook_url, str) or not alert_webhook_url.startswith(WEBHOOK_PREFIXES):
        raise ConfigError(f"alert_webhook_url in {CONFIG_FILE} must be a Discord webhook URL or empty.")

    try:
        # Never poll faster than once a minute, to protect the API quota.
        poll_interval = max(60, int(data["poll_interval_seconds"]))
    except (TypeError, ValueError):
        raise ConfigError(f"poll_interval_seconds in {CONFIG_FILE} must be a number.") from None

    return Config(
        webhook_url=webhook_url,
        alert_webhook_url=alert_webhook_url,
        message=str(data["message"]),
        poll_interval_seconds=poll_interval,
    )
