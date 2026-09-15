"""
draw_slot_overlay.py

Draws the configured SLOT_ROIS boxes (from slot_occupancy.py) onto a
zone's saved reference frame, so you can visually check whether the
coordinates actually line up with real slot positions — instead of
guessing blind.

Workflow:
1. Guess rough coordinates in slot_occupancy.py's SLOT_ROIS.
2. Run this script -> look at the output overlay image.
3. If a box is in the wrong place, adjust the numbers and rerun.
4. Repeat until every box sits on its real slot.

Usage:
    python3 draw_slot_overlay.py zone-c
"""

import os
import sys
import cv2

from slot_occupancy import SLOT_ROIS, REFERENCE_DIR

OVERLAY_DIR = os.path.expanduser("~/smartparking/static/overlays")


def draw_overlay(zone: str):
    ref_path = os.path.join(REFERENCE_DIR, f"{zone}_empty.jpg")
    if not os.path.exists(ref_path):
        print(f"[FAIL] No reference frame for {zone} — run: python3 slot_occupancy.py capture {zone}")
        return

    image = cv2.imread(ref_path)
    if image is None:
        print(f"[FAIL] Could not read {ref_path}")
        return

    slots = SLOT_ROIS.get(zone, {})
    if not slots:
        print(f"[FAIL] No slots configured for {zone} in SLOT_ROIS")
        return

    any_drawn = False
    for slot_id, roi in slots.items():
        if roi is None:
            print(f"  slot {slot_id}: no ROI set yet — skipping")
            continue
        x1, y1, x2, y2 = roi
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"slot {slot_id}"
        # Put the label just above the box; if that goes off-frame, put it inside instead
        label_y = y1 - 6 if y1 - 6 > 10 else y1 + 16
        cv2.putText(image, label, (x1, label_y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.4, (0, 255, 0), 1, cv2.LINE_AA)
        any_drawn = True

    if not any_drawn:
        print(f"[INFO] No ROIs set for {zone} yet — nothing to draw. Fill in SLOT_ROIS first.")
        return

    os.makedirs(OVERLAY_DIR, exist_ok=True)
    out_path = os.path.join(OVERLAY_DIR, f"{zone}_overlay.jpg")
    cv2.imwrite(out_path, image)
    print(f"[OK] Overlay saved -> {out_path}")
    print("View it (e.g. over VNC): eog " + out_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 draw_slot_overlay.py <zone>")
        sys.exit(1)
    draw_overlay(sys.argv[1])
