"""Posts messages to a Discord channel through a webhook.

Discord answers a webhook post with one of three outcomes we care about:
success, "slow down" (429 with a retry_after), or a permanent error such as
the webhook having been deleted (404).
"""

import logging
import time

import requests

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


class WebhookError(Exception):
    """Raised when Discord refuses the post and retrying won't help."""


def post_message(webhook_url: str, content: str) -> None:
    """Post `content` to the channel, retrying on rate limits and network hiccups."""
    payload = {
        "content": content,
        # Never let message text ping @everyone, @here, roles or users.
        "allowed_mentions": {"parse": []},
    }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            # wait=true makes Discord confirm the message was created before replying,
            # so success here really means it's in the channel.
            resp = requests.post(webhook_url, params={"wait": "true"}, json=payload, timeout=15)
        except requests.RequestException as e:
            if attempt == MAX_ATTEMPTS:
                raise
            delay = 2**attempt
            log.warning("Discord post failed (%s); retrying in %ss.", e, delay)
            time.sleep(delay)
            continue

        if resp.ok:
            return

        if resp.status_code == 429:
            # Discord says exactly how long to wait, in seconds.
            delay = float(resp.json().get("retry_after", 5))
        elif resp.status_code >= 500:
            delay = 2**attempt
        else:
            # 400/401/403/404: bad payload or the webhook was deleted. Retrying won't fix it.
            raise WebhookError(f"Discord rejected the post ({resp.status_code}): {resp.text[:200]}")

        if attempt == MAX_ATTEMPTS:
            raise WebhookError(f"Discord kept failing ({resp.status_code}) after {MAX_ATTEMPTS} attempts.")
        log.warning("Discord returned %s; retrying in %.1fs.", resp.status_code, delay)
        time.sleep(delay)


def announce_video(webhook_url: str, message: str, video_id: str) -> None:
    """Post the announcement."""
    post_message(webhook_url, f"{message} https://youtu.be/{video_id}")
