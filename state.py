"""Remembers which videos have already been announced.

state.json looks like:
    {"version": 1, "announced": ["dQw4w9WgXcQ", ...]}

Only video IDs that were posted to Discord (or were already unlisted when the
notifier was first set up) are stored. Entire workflow: video uploaded as private,
YouTube processes it, then the video gets manually set to unlisted.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field

from config import APP_DIR, STATE_FILE

log = logging.getLogger(__name__)

STATE_VERSION = 1


@dataclass
class State:
    announced: set[str] = field(default_factory=set)


def load_state() -> State | None:
    """Return the saved state, or None if this is the first run."""
    if not STATE_FILE.exists():
        return None

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return State(announced=set(data["announced"]))
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        # Atomic writes make this very unlikely. If it happens anyway, keep the
        # bad file for inspection and seed again rather than reposting old videos.
        backup = STATE_FILE.with_suffix(".json.corrupt")
        os.replace(STATE_FILE, backup)
        log.warning("State file was unreadable (%s); moved it to %s and reseeding.", e, backup)
        return None


def save_state(state: State) -> None:
    """Write state.json atomically: a crash leaves either the old or new file, never half of one."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")

    payload = {"version": STATE_VERSION, "announced": sorted(state.announced)}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())  # make sure the bytes are on disk before the swap

    # os.replace is atomic on Windows, but it fails if another program (antivirus,
    # search indexer, backup tool) briefly has state.json open. Retry a few times.
    for attempt in range(5):
        try:
            os.replace(tmp, STATE_FILE)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2 * (attempt + 1))
