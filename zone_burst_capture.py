"""
zone_burst_capture.py

Runs a background burst of zone camera captures after a plate is read,
so the dashboard's "Zone cameras" panel shows fresh frames from all
three zones during/after an entry event, instead of only whenever the
next scheduled capture happens to fire.

Reuses esp32_cameras.py's fetch_all_zones() directly — same files
(zone_a_check.jpg / zone_b_check.jpg / zone_c_check.jpg), same
save location, so the existing dashboard polling picks these up with
no changes needed on that end.

Usage (from anpr.py):
    from zone_burst_capture import start_capture_burst
    start_capture_burst()   # fire-and-forget, runs in a background thread
"""

import threading
import time
import logging
import os

from esp32_cameras import fetch_all_zones

logger = logging.getLogger(__name__)

BURST_DURATION_SEC = 90   # total time to keep capturing after a plate read
BURST_INTERVAL_SEC = 10   # time between captures during the burst

_burst_lock = threading.Lock()
_burst_active = False


def _run_burst(duration_sec: int, interval_sec: int):
    global _burst_active

    end_time = time.time() + duration_sec
    logger.info(f"Burst capture started ({duration_sec}s at {interval_sec}s intervals)")

        while time.time() < end_time:
        try:
            # Tell esp32_cameras.py to save the images into the dashboard's static folder
            statuses = fetch_all_zones(base_path=os.path.expanduser("~/smartparking/dashboard/static"))
            logger.info(f"Burst capture: {statuses}")
        except Exception as e:
            logger.error(f"Burst capture iteration failed: {e}")
        time.sleep(interval_sec)

    logger.info("Burst capture finished")
    with _burst_lock:
        _burst_active = False


def start_capture_burst(duration_sec: int = BURST_DURATION_SEC,
                         interval_sec: int = BURST_INTERVAL_SEC) -> bool:
    """
    Starts a background burst-capture thread. Safe to call every time a
    plate is read — if a burst is already running, this just extends
    coverage by letting the existing one continue rather than stacking
    a second thread on top of it (avoids piling up concurrent
    fetch_all_zones() calls hitting the same cameras at once).

    Returns True if a new burst was started, False if one was already
    running (and therefore this call was a no-op).
    """
    global _burst_active

    with _burst_lock:
        if _burst_active:
            logger.info("Burst capture already running — skipping duplicate trigger")
            return False
        _burst_active = True

    thread = threading.Thread(
        target=_run_burst, args=(duration_sec, interval_sec), daemon=True
    )
    thread.start()
    return True
