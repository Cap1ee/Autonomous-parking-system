import cv2
import os
import numpy as np

# ─── CONFIG ───────────────────────────────────────────────────────────────────
STATIC_DIR = os.path.expanduser("~/smartparking/static")
REFERENCE_DIR = os.path.join(STATIC_DIR, "references")

# Switched from a fixed pixel count to a percentage.
# If 15% of the pixels in the ROI change, we consider it occupied.
OCCUPANCY_RATIO_THRESH = 0.15 

SLOT_ROIS = {
    "zone-a": {1: None, 2: None, 3: None},   # Still needs calibration
    "zone-b": {4: None, 5: None, 6: None},   # Still needs calibration
    "zone-c": {
        7: (72, 154, 139, 207),
        8: (156, 155, 300, 212),
    },
}
# ──────────────────────────────────────────────────────────────────────────────

def capture_reference(zone):
    """Captures an empty-lot baseline frame for the given zone."""
    from esp32_cameras import fetch_zone_frame
    
    os.makedirs(REFERENCE_DIR, exist_ok=True)
    ref_path = os.path.join(REFERENCE_DIR, f"{zone}_empty.jpg")
    
    print(f"Capturing reference frame for {zone}...")
    success = fetch_zone_frame(zone, ref_path)
    
    if success:
        print(f"✅ Saved reference frame to {ref_path}")
    else:
        print(f"❌ Failed to capture reference frame for {zone}")
    return success


def check_slot_occupancy(zone, slot_id, current_frame_path):
    """
    Diffs a live frame's ROI against the empty reference.
    Returns True (occupied), False (empty), or None (error/no ROI).
    """
    if zone not in SLOT_ROIS or slot_id not in SLOT_ROIS[zone]:
        print(f"  [WARN] Zone {zone} or slot {slot_id} not configured in SLOT_ROIS")
        return None
        
    roi = SLOT_ROIS[zone][slot_id]
    if roi is None:
        return None
        
    ref_path = os.path.join(REFERENCE_DIR, f"{zone}_empty.jpg")
    if not os.path.exists(ref_path):
        print(f"  [WARN] Reference frame not found at {ref_path}")
        return None
        
    if not os.path.exists(current_frame_path):
        print(f"  [WARN] Current frame not found at {current_frame_path}")
        return None
        
    # Load images
    ref_img = cv2.imread(ref_path, cv2.IMREAD_GRAYSCALE)
    curr_img = cv2.imread(current_frame_path, cv2.IMREAD_GRAYSCALE)
    
    if ref_img is None or curr_img is None:
        print("  [WARN] Failed to load images for occupancy check")
        return None
        
    # Extract the ROI coordinates
    x1, y1, x2, y2 = roi
    roi_area = (x2 - x1) * (y2 - y1)
    
    # Crop the ROI from both images
    ref_roi = ref_img[y1:y2, x1:x2]
    curr_roi = curr_img[y1:y2, x1:x2]
    
    # Compute the absolute difference and threshold it
    diff = cv2.absdiff(ref_roi, curr_roi)
    _, th = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
    
    # Count how many pixels changed
    changed_px = cv2.countNonZero(th)
    
    # Calculate the ratio of changed pixels to total ROI area
    ratio = changed_px / roi_area
    is_occupied = ratio > OCCUPANCY_RATIO_THRESH
    
    print(f"  [Occupancy] Slot {slot_id}: {changed_px}/{roi_area} px changed ({ratio*100:.1f}%) -> {'OCCUPIED' if is_occupied else 'EMPTY'}")
    
    return is_occupied
