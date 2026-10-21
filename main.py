"""Entry point: watches the channel and announces newly unlisted videos on Discord.

Usage:
    python main.py --auth    one-time Google sign-in (run in a normal terminal)
    python main.py --once    check once and exit (handy for testing)
    pythonw main.py          run forever in the background (what Task Scheduler starts)
"""

import argparse
import logging
import msvcrt
import sys
import time
from logging.handlers import RotatingFileHandler

import requests

from config import APP_DIR, LOCK_FILE, LOG_FILE, Config, ConfigError, load_config
from state import State, load_state, save_state
from webhook import WebhookError, announce_video, post_message
from youtube import AuthError, YouTubeClient, authorize_interactive

log = logging.getLogger("notifier")

# After an error, wait 1, 2, 4... minutes before trying again, but never longer
# than the normal poll interval.
MIN_RETRY_SECONDS = 60


def setup_logging() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        # Keeps notifier.log under 1 MB, plus up to 3 older copies.
        RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    ]
    # pythonw has no console (sys.stderr is None), so only log to the screen when there is one.
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def acquire_single_instance_lock():
    """Return an open, locked file handle, or None if another copy is already running.

    Windows releases the lock automatically when the process exits, even after a crash.
    """
    APP_DIR.mkdir(parents=True, exist_ok=True)
    handle = open(LOCK_FILE, "a+")
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    return handle


def check_once(client: YouTubeClient, cfg: Config, state: State | None) -> State:
    """Do one check and return the updated state. A state of None means first run."""
    statuses = client.recent_upload_statuses()
    unlisted = [vid for vid, status in statuses.items() if status == "unlisted"]

    if state is None:
        # First run: treat everything that's already unlisted as announced, without posting.
        state = State(announced=set(unlisted))
        save_state(state)
        log.info("First run: recorded %d unlisted video(s) without announcing them.", len(unlisted))
        return state

    for vid in unlisted:
        if vid in state.announced:
            continue
        announce_video(cfg.webhook_url, cfg.message, vid, client.video_description(vid))
        # Save after each post, so a crash mid-batch never causes a repost.
        state.announced.add(vid)
        save_state(state)
        log.info("Announced %s.", vid)
    return state


def run_forever(cfg: Config) -> None:
    state = load_state()
    client: YouTubeClient | None = None
    auth_alert_sent = False
    failures = 0

    while True:
        try:
            if client is None:
                client = YouTubeClient()
            state = check_once(client, cfg, state)
            if auth_alert_sent:
                log.info("YouTube sign-in is working again.")
            auth_alert_sent = False
            failures = 0
        except AuthError as e:
            # Rebuild the client next time, so a fresh `--auth` is picked up without a restart.
            client = None
            failures += 1
            log.error("%s", e)
            if not auth_alert_sent:
                try:
                    post_message(cfg.alert_webhook_url, f"Rerun notifier needs attention: {e}")
                    auth_alert_sent = True
                except (WebhookError, requests.RequestException) as post_err:
                    log.error("Couldn't send the sign-in alert to Discord: %s", post_err)
        except (WebhookError, requests.RequestException, OSError) as e:
            # Network down, YouTube or Discord having issues, PC just woke from sleep...
            # The video isn't marked as announced, so it's retried on the next check.
            failures += 1
            log.warning("Check failed: %s", e)
        except Exception:
            # Anything unexpected: log the full traceback but keep the loop alive.
            failures += 1
            log.exception("Unexpected error during check.")

        if failures:
            delay = min(MIN_RETRY_SECONDS * 2 ** (failures - 1), cfg.poll_interval_seconds)
        else:
            delay = cfg.poll_interval_seconds
        time.sleep(delay)


def main() -> int:
    parser = argparse.ArgumentParser(description="Announce newly unlisted YouTube videos on Discord.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--auth", action="store_true", help="sign in to Google (opens a browser)")
    mode.add_argument("--once", action="store_true", help="check once and exit")
    args = parser.parse_args()

    setup_logging()

    if args.auth:
        try:
            authorize_interactive()
        except AuthError as e:
            log.error("%s", e)
            return 1
        log.info("Signed in. The notifier can now run in the background.")
        return 0

    lock = acquire_single_instance_lock()
    if lock is None:
        log.info("Another copy of the notifier is already running; exiting.")
        return 0

    try:
        cfg = load_config()
    except ConfigError as e:
        log.error("%s", e)
        return 1

    if args.once:
        try:
            check_once(YouTubeClient(), cfg, load_state())
        except (AuthError, WebhookError, requests.RequestException) as e:
            log.error("%s", e)
            return 1
        return 0

    log.info("Notifier started; checking every %d seconds.", cfg.poll_interval_seconds)
    run_forever(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
