"""
esp32_cameras.py

Fetches JPEG snapshots from the three zone ESP32-CAM units over HTTP.
Each camera has a static IP on the home Wi-Fi network and serves a
single-frame JPEG at /capture.

Concurrent fetching, response validation, and automatic home/hotspot
IP fallback so this doesn't need manual editing before demo day.
"""

import os
import time
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging. If imported by anpr.py, anpr.py can override this config.
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Each zone has two possible IPs: home Wi-Fi (primary) and the iPhone
# hotspot (fallback), matching the Pi's own home/hotspot nmcli setup.
#
# NOTE: iPhone Personal Hotspot hands out 172.20.10.x with a /28 mask
# (255.255.255.240) — only .2 through .14 are valid host addresses.
# These must match the hotspot_ip values flashed onto each ESP32 in
# wifi_connect.ino.
ZONE_CAMERAS = {
    "zone-a": ["192.168.1.201", "172.20.10.11"],
    "zone-b": ["192.168.1.202", "172.20.10.12"],
    "zone-c": ["192.168.1.203", "172.20.10.13"],
}

REQUEST_TIMEOUT_SEC = 15
MAX_ATTEMPTS = 2            # total attempts per IP
RETRY_DELAY_SEC = 1
MIN_VALID_IMAGE_BYTES = 1500  # calibrated against a real QVGA (320x240) frame
                               # from zone-c (~2.6KB on a plain scene) — all
                               # three zones now run QVGA, so this applies uniformly


def _try_fetch(url: str, expanded_path: str) -> bool:
    """Single fetch attempt sequence (with retries) against one URL."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT_SEC, headers={'Connection': 'close'})
            resp.raise_for_status()

            # ESP32-CAMs sometimes return 200 OK with broken/empty payloads
            content_type = resp.headers.get("Content-Type", "")
            if "image" not in content_type:
                raise ValueError(f"Unexpected Content-Type: {content_type}")

            if len(resp.content) < MIN_VALID_IMAGE_BYTES:
                raise ValueError(f"Image payload too small ({len(resp.content)} bytes)")

            with open(expanded_path, "wb") as f:
                f.write(resp.content)

            logger.info(f"Captured {url} -> {expanded_path}")
            return True

        except (requests.RequestException, OSError, ValueError) as e:
            logger.warning(f"{url} fetch failed (attempt {attempt}/{MAX_ATTEMPTS}): {e}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAY_SEC)

    return False


def fetch_zone_frame(zone: str, save_path: str) -> bool:
    """
    Fetch a single JPEG snapshot from the given zone's ESP32-CAM and
    save it to save_path. Tries the home Wi-Fi IP first, then the
    hotspot IP, so no manual IP edit is needed before demo day.

    Returns True on success, False otherwise.
    """
    ips = ZONE_CAMERAS.get(zone)
    if not ips:
        logger.error(f"Unknown zone '{zone}'")
        return False

    expanded_path = os.path.expanduser(save_path)
    save_dir = os.path.dirname(expanded_path)
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)

    for ip in ips:
        url = f"http://{ip}/capture"
        if _try_fetch(url, expanded_path):
            return True
        logger.warning(f"{zone}: {ip} unreachable, trying next IP if available")

    logger.error(f"{zone} failed on all known IPs {ips}")
    return False


def fetch_all_zones(base_path: str = "~/smartparking/static") -> dict:
    """
    Fetches frames from all configured zones concurrently.
    Returns a dict mapping zone names to boolean success status.
    """
    results = {}
    with ThreadPoolExecutor(max_workers=len(ZONE_CAMERAS)) as executor:
        future_to_zone = {}

        for zone in ZONE_CAMERAS:
            out_path = f"{base_path}/{zone.replace('-', '_')}_check.jpg"
            future = executor.submit(fetch_zone_frame, zone, out_path)
            future_to_zone[future] = zone

        for future in as_completed(future_to_zone):
            zone = future_to_zone[future]
            try:
                results[zone] = future.result()
            except Exception as e:
                logger.error(f"Unexpected error processing {zone}: {e}")
                results[zone] = False

    return results


if __name__ == "__main__":
    # Quick manual test from the Pi: python3 esp32_cameras.py
    logger.info("Starting manual capture test for all zones...")
    start_time = time.time()

    statuses = fetch_all_zones()

    elapsed = time.time() - start_time
    logger.info(f"Capture batch finished in {elapsed:.2f} seconds.")
    for zone, ok in statuses.items():
        status_str = "OK" if ok else "FAILED"
        logger.info(f"{zone}: {status_str}")
