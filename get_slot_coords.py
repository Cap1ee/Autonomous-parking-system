"""
get_slot_coords.py

Click-to-coordinates helper for calibrating SLOT_ROIS in slot_occupancy.py.

Opens a zone's reference frame and lets you click two corners per slot
(top-left, then bottom-right). Prints the (x1, y1, x2, y2) tuple for
each slot as you go, and a ready-to-paste SLOT_ROIS dict at the end.

Usage:
    python3 get_slot_coords.py zone-c 7 8

(pass the zone name, then the slot IDs in this zone, in the order you
want to click them)
"""

import sys
import os
import cv2

from slot_occupancy import REFERENCE_DIR

clicks = []
current_slot = None
results = {}
window_name = "Click top-left then bottom-right for each slot (q to quit)"


def on_click(event, x, y, flags, param):
    global clicks
    if event == cv2.EVENT_LBUTTONDOWN:
        clicks.append((x, y))
        print(f"  clicked: ({x}, {y})")


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 get_slot_coords.py <zone> <slot_id> [slot_id ...]")
        sys.exit(1)

    zone = sys.argv[1]
    slot_ids = [int(s) for s in sys.argv[2:]]

    ref_path = os.path.join(REFERENCE_DIR, f"{zone}_empty.jpg")
    if not os.path.exists(ref_path):
        print(f"[FAIL] No reference frame for {zone} at {ref_path}")
        print(f"Run: python3 slot_occupancy.py capture {zone}")
        sys.exit(1)

    base_image = cv2.imread(ref_path)
    if base_image is None:
        print(f"[FAIL] Could not read {ref_path}")
        sys.exit(1)

    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, on_click)

    global clicks
    for slot_id in slot_ids:
        clicks = []
        print(f"\n=== Slot {slot_id} === click top-left corner, then bottom-right corner.")
        display = base_image.copy()

        while True:
            frame = display.copy()
            for pt in clicks:
                cv2.circle(frame, pt, 3, (0, 255, 0), -1)
            cv2.imshow(window_name, frame)
            key = cv2.waitKey(20) & 0xFF

            if key == ord("q"):
                cv2.destroyAllWindows()
                print("\nQuit early.")
                print_summary(results)
                sys.exit(0)

            if len(clicks) >= 2:
                x1, y1 = clicks[0]
                x2, y2 = clicks[1]
                # Normalize so x1<x2, y1<y2 regardless of click order
                x1, x2 = sorted((x1, x2))
                y1, y2 = sorted((y1, y2))
                results[slot_id] = (x1, y1, x2, y2)
                print(f"  slot {slot_id}: ({x1}, {y1}, {x2}, {y2})")
                cv2.rectangle(display, (x1, y1), (x2, y2), (0, 255, 0), 2)
                break

    cv2.destroyAllWindows()
    print_summary(results)


def print_summary(results):
    if not results:
        return
    print("\n=== Paste into SLOT_ROIS ===")
    for slot_id, roi in results.items():
        print(f"        {slot_id}: {roi},")


if __name__ == "__main__":
    main()
