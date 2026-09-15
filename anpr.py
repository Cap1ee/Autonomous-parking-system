import cv2
import numpy as np 
import sqlite3
import os
import time
import re
import logging
from difflib import get_close_matches
from datetime import datetime

import easyocr
from ultralytics import YOLO
import RPi.GPIO as GPIO
from RPLCD.i2c import CharLCD
from picamera2 import Picamera2

#from zone_burst_capture import start_capture_burst
logging.getLogger("urllib3").setLevel(logging.ERROR)

READER   = None
DETECTOR = None

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MOTION_THRESH           = 5000
COOLDOWN_SEC            = 10
STABILIZATION_DELAY_SEC = 3       # Wait 3 seconds for vehicle to stabilize
DB_PATH                 = os.path.expanduser("~/smartparking/database/parking.db")
CAPTURE_PATH = os.path.expanduser("~/smartparking/dashboard/static/capture.jpg")

# Camera stream sizes
# MAIN_SIZE is 4:3 (matches the IMX219 sensor's native aspect and the old
# rpicam-still --width 800 --height 600 setup, and matches LORES_SIZE's
# own 4:3 ratio too). Using a 16:9 size here (e.g. the common 1280x720)
# forces Picamera2 to crop the top/bottom off the full sensor image to
# fit that ratio — which was silently cutting into the entry-gate FOV
# and caused a real drop in plate-detection rate versus the old pipeline.
MAIN_SIZE  = (1280, 960)   # full-res, 4:3, used only for the stabilized OCR frame
LORES_SIZE = (320, 240)    # small/cheap stream, 4:3, used for motion detection AND
                            # as the "Latest capture" dashboard preview every loop

# Servo
SERVO_PIN      = 13        # GPIO 13 (Physical Pin 33)
SERVO_FREQ     = 50        # Hz
SERVO_CLOSED   = 2.5      # Duty cycle for 0° (gate closed)
SERVO_OPEN     = 7.0      # Duty cycle for 90° (gate open)
GATE_OPEN_SEC  = 5        # How long gate stays open

# YOLO Plate Detector
MODEL_PATH  = os.path.expanduser('~/smartparking/models/best_ncnn_model')
PLATE_CONF  = 0.4
PLATE_PAD   = 20

# LCD
LCD_ADDRESS    = 0x27
LCD_COLS       = 20
LCD_ROWS       = 4

# Faculty → physical zone group. Medicine and Computing SHARE zone A
# (slots 1-6, FOC building); Engineering has its own zone B (slots 7-8,
# FOE building). This mirrors the real KDU layout, not a 1:1
# faculty-per-slot split.
FACULTY_GROUP = {
    "Medicine":    "A",
    "Computing":   "A",
    "Engineering": "B",
}

# Zone overflow priority — tries the faculty's own zone first, then
# falls back to the other zone if full. Both directions overflow here,
# so effectively slots 1-8 are one pool with a preferred half per faculty.
ZONE_OVERFLOW = {
    "A": ["A", "B"],
    "B": ["B", "A"],
}
# ──────────────────────────────────────────────────────────────────────────────


# ─── HARDWARE & CAMERA INIT ───────────────────────────────────────────────────
def init_servo():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)  # suppresses the harmless "channel already in use"
                              # warning that fires if a previous run's GPIO.cleanup()
                              # didn't happen (e.g. after a hard crash or double Ctrl+C)
    GPIO.setup(SERVO_PIN, GPIO.OUT)
    pwm = GPIO.PWM(SERVO_PIN, SERVO_FREQ)
    pwm.start(SERVO_CLOSED)   # Start with gate closed
    time.sleep(0.5)
    pwm.ChangeDutyCycle(0)
    return pwm


def init_lcd():
    lcd = CharLCD(
        i2c_expander='PCF8574',
        address=LCD_ADDRESS,
        port=1,
        cols=LCD_COLS,
        rows=LCD_ROWS,
        dotsize=8
    )
    lcd.clear()
    return lcd


def init_camera():
    """
    Initializes a dual-stream Picamera2 pipeline:
      - "main"  (1280x720, BGR888): only pulled once per detection, after
        the stabilization delay, for the actual YOLO/OCR frame.
      - "lores" (320x240, YUV420): pulled every loop iteration for motion
        detection and the "Latest capture" dashboard preview. Picamera2
        requires the lores stream to be YUV, not BGR — we take advantage
        of that by using the Y (luma) plane directly as a ready-made
        grayscale frame for motion diffing, skipping the BGR->gray
        conversion entirely (see get_lores_gray()).
    """
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(
        main={"format": "BGR888", "size": MAIN_SIZE},
        lores={"format": "YUV420", "size": LORES_SIZE},
    )
    picam2.configure(config)
    picam2.start()
    time.sleep(1)  # Allow camera sensor warm-up
    return picam2


def get_lores_gray(picam2):
    """
    Grabs the lores YUV420 frame and returns just its Y (luma) plane —
    already a single-channel grayscale image, no cv2.cvtColor needed.
    """
    yuv = picam2.capture_array("lores")
    h = LORES_SIZE[1]
    # We use np.ascontiguousarray to fix a memory issue so cv2.imwrite works
    return np.ascontiguousarray(yuv[:h, :])

def open_gate(pwm):
    pwm.ChangeDutyCycle(SERVO_OPEN)
    time.sleep(0.3)
    pwm.ChangeDutyCycle(0)   # Stop sending signal to prevent servo jitter


def close_gate(pwm):
    pwm.ChangeDutyCycle(SERVO_CLOSED)
    time.sleep(0.3)
    pwm.ChangeDutyCycle(0)


# ─── LCD DISPLAY ──────────────────────────────────────────────────────────────
def lcd_granted(lcd, owner, slot_id, zone):
    """Show ACCESS GRANTED for 2s then welcome screen."""
    lcd.clear()
    lcd.cursor_pos = (1, 3)
    lcd.write_string('ACCESS GRANTED')
    time.sleep(2)

    lcd.clear()
    name_short = owner[:12] if len(owner) > 12 else owner
    lcd.cursor_pos = (0, 0)
    lcd.write_string(f'Welcome {name_short}')
    lcd.cursor_pos = (1, 0)
    # zone is already the physical zone letter (A/B) returned by find_slot() —
    # matches the dashboard's own "Zone A"/"Zone B" labels directly now.
    lcd.write_string(f'Slot: {slot_id}  Zone: {zone}')
    lcd.cursor_pos = (3, 0)
    lcd.write_string('Gate Opening...')


def lcd_denied(lcd, plate):
    """Show ACCESS DENIED with plate number."""
    lcd.clear()
    lcd.cursor_pos = (1, 3)
    lcd.write_string('ACCESS DENIED')
    lcd.cursor_pos = (2, 0)
    plate_line = f'Plate: {plate}'
    lcd.write_string(plate_line[:20])


def lcd_full(lcd):
    """Show parking full message."""
    lcd.clear()
    lcd.cursor_pos = (1, 3)
    lcd.write_string('PARKING IS FULL')
    lcd.cursor_pos = (2, 2)
    lcd.write_string('Try again later')


def lcd_standby(lcd):
    """Idle screen shown when system is waiting."""
    lcd.clear()
    lcd.cursor_pos = (0, 4)
    lcd.write_string('KDU SmartPark')
    lcd.cursor_pos = (1, 2)
    lcd.write_string('Waiting for car...')


def lcd_scanning(lcd):
    """Show while OCR is running."""
    lcd.clear()
    lcd.cursor_pos = (1, 3)
    lcd.write_string('Scanning Plate')
    lcd.cursor_pos = (2, 4)
    lcd.write_string('Please wait...')


# ─── DATABASE ─────────────────────────────────────────────────────────────────
def get_db():
    return sqlite3.connect(DB_PATH)


def update_heartbeat(state):
    try:
        con = get_db()
        con.execute(
            "UPDATE system_status SET last_heartbeat=?, anpr_state=? WHERE id=1",
            (datetime.now().isoformat(), state)
        )
        con.commit()
        con.close()
    except sqlite3.Error as e:
        print(f"  [WARN] Heartbeat write failed: {e}")


def lookup_plate(plate):
    con = get_db()
    cur = con.cursor()

    cur.execute("SELECT owner_name, role, faculty FROM whitelist WHERE plate=?", (plate,))
    row = cur.fetchone()
    if row:
        con.close()
        return row

    cur.execute("SELECT plate, owner_name, role, faculty FROM whitelist")
    all_plates = cur.fetchall()
    con.close()

    plates = [r[0] for r in all_plates]
    matches = get_close_matches(plate, plates, n=1, cutoff=0.8)
    if matches:
        for r in all_plates:
            if r[0] == matches[0]:
                print(f"  [FUZZY] '{plate}' matched to '{matches[0]}'")
                return r[1], r[2], r[3]

    return None


def find_slot(faculty, role=None):
    """
    Returns (slot_id, zone_used) using zone overflow logic.
    If the driver is a Dean, it will look for their specific reserved slot first.
    Otherwise, it skips any reserved slots.
    """
    con = get_db()
    cur = con.cursor()

    # 1. If the driver is a Dean, look for their reserved slot first
    if role and role.startswith("Dean"):
        cur.execute(
            "SELECT slot_id, zone FROM parking_slots WHERE reserved_for=? AND is_occupied=0 LIMIT 1",
            (role,)
        )
        row = cur.fetchone()
        if row:
            con.close()
            return row[0], row[1]

    # 2. For normal staff, find a non-reserved slot
    primary_zone = FACULTY_GROUP[faculty]
    for zone in ZONE_OVERFLOW[primary_zone]:
        cur.execute(
            "SELECT slot_id FROM parking_slots WHERE zone=? AND is_occupied=0 AND reserved_for IS NULL ORDER BY slot_id LIMIT 1",
            (zone,)
        )
        row = cur.fetchone()
        if row:
            con.close()
            return row[0], zone

    con.close()
    return None, None

def assign_slot(slot_id, plate, faculty):
    """
    faculty is now written dynamically per-assignment (whoever actually
    parked there), not fixed per-slot, since slots are shared within a
    zone. Cleared back to NULL when the slot is freed.
    """
    con = get_db()
    con.execute(
        "UPDATE parking_slots SET is_occupied=1, plate=?, faculty=? WHERE slot_id=?",
        (plate, faculty, slot_id)
    )
    con.commit()
    con.close()


def log_entry(plate, owner_name, faculty, slot_id):
    con = get_db()
    con.execute(
        "INSERT INTO entry_log (plate, owner_name, faculty, action, slot_id, timestamp) VALUES (?,?,?,?,?,?)",
        (plate, owner_name, faculty, "entry", slot_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    con.commit()
    con.close()


# ─── MOTION & YOLO DETECTION ──────────────────────────────────────────────────
def motion_detected(prev_gray, curr_gray):
    """
    Computes motion between two lores (320x240) grayscale Y-plane arrays
    (see get_lores_gray()). Already single-channel, so no cv2.cvtColor
    is needed here anymore — one less step than the BGR888 version.
    """
    if prev_gray is None or curr_gray is None:
        return False
    diff = cv2.absdiff(prev_gray, curr_gray)
    _, th = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
    return cv2.countNonZero(th) > MOTION_THRESH


def detect_plate_region(image):
    global DETECTOR
    results = DETECTOR(image, imgsz=640, conf=PLATE_CONF, verbose=False)
    if not results or len(results[0].boxes) == 0:
        print('  [YOLO] No plate detected')
        return None
    boxes = results[0].boxes
    best_idx = int(boxes.conf.argmax())
    x1, y1, x2, y2 = map(int, boxes.xyxy[best_idx].tolist())
    h, w = image.shape[:2]
    x1 = max(0, x1 - PLATE_PAD)
    y1 = max(0, y1 - PLATE_PAD)
    x2 = min(w, x2 + PLATE_PAD)
    y2 = min(h, y2 + PLATE_PAD)
    conf = float(boxes.conf[best_idx])
    print(f'  [YOLO] Plate at ({x1},{y1})-({x2},{y2})  conf={conf:.2f}')
    crop = image[y1:y2, x1:x2]
    cv2.imwrite(os.path.expanduser('~/smartparking/dashboard/static/plate_crop.jpg'), crop)
    return crop


# ─── OCR ──────────────────────────────────────────────────────────────────────
def preprocess_for_ocr(region):
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    return enhanced


def run_ocr(region):
    global READER

    enhanced = preprocess_for_ocr(region)
    results = READER.readtext(enhanced)
    if not results:
        return None

    results = [r for r in results if r[2] >= 0.3]
    if not results:
        print("  [OCR] All results below confidence threshold")
        return None

    results.sort(key=lambda r: (r[0][0][1], r[0][0][0]))
    full_text = ''.join([r[1] for r in results])
    avg_confidence = sum(r[2] for r in results) / len(results)

    print(f"  [OCR] Raw regions: {[r[1] for r in results]}")
    print(f"  [OCR] Combined: '{full_text}'  Avg confidence: {avg_confidence:.2f}")

    return clean_plate(full_text)


def clean_plate(text):
    text = text.upper()
    text = re.sub(r'[^A-Z0-9\-]', '', text)
    text = text.replace('O', '0') if text.count('0') == 0 and text.count('O') > 0 else text
    return text


# ─── MAIN LOOP ────────────────────────────────────────────────────────────────
def main():
    print("=== Smart Parking ANPR Starting ===")
    print(f"DB: {DB_PATH}")
    print(f"Motion threshold: {MOTION_THRESH}  |  Cooldown: {COOLDOWN_SEC}s")
    print("Press Ctrl+C to stop.\n")

    # Init hardware
    print("Initialising servo...")
    pwm = init_servo()
    print("Servo ready.")

    print("Initialising LCD...")
    lcd = init_lcd()
    lcd_standby(lcd)
    print("LCD ready.")

    print("Initialising Pi Camera dual stream (main=720p, lores=320x240)...")
    picam2 = init_camera()
    print("Camera stream ready.")

    global READER, DETECTOR
    print("Loading EasyOCR model (one-time)...")
    READER = easyocr.Reader(['en'], gpu=False)
    print("EasyOCR ready!")

    print("Loading YOLO plate detector...")
    DETECTOR = YOLO(MODEL_PATH, task='detect')
    print("YOLO ready!\n")

    update_heartbeat("starting")
    last_trigger = 0

    # Grab initial lores reference frame (Y-plane grayscale) directly from the camera buffer
    prev_frame = get_lores_gray(picam2)

    try:
        while True:
            now = time.time()
            update_heartbeat("idle")

            # Cheap lores grayscale frame every loop — used for motion diff
            # AND kept as the dashboard's "Latest capture" preview so that
            # panel stays live even when idle. Note: since lores is YUV
            # (Picamera2 requirement) and we use its Y-plane directly, this
            # idle preview is grayscale — it becomes full color again the
            # moment a real detection pulls the "main" stream below.
            curr_frame = get_lores_gray(picam2)
            cv2.imwrite(CAPTURE_PATH, curr_frame)

            # Honor cooldown period
            if (now - last_trigger) < COOLDOWN_SEC:
                prev_frame = curr_frame
                time.sleep(0.05)
                continue

            # Motion check on the small lores frames
            if motion_detected(prev_frame, curr_frame):
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Motion detected!")

                # Set cooldown from the moment motion was detected, not
                # after stabilization + processing — keeps COOLDOWN_SEC's
                # meaning consistent with the pre-Picamera2 version.
                last_trigger = now

                print(f"  Waiting {STABILIZATION_DELAY_SEC} seconds for car to stabilize...")
                update_heartbeat("stabilizing")
                lcd_scanning(lcd)

                # Pause to let vehicle settle & exposure adjust
                time.sleep(STABILIZATION_DELAY_SEC)

                # Now pull the one full-res frame for this detection —
                # this is the only place "main" (1280x720) gets grabbed,
                # so the per-loop cost stays at the cheap lores size.
                stabilized_frame = picam2.capture_array("main")
                cv2.imwrite(CAPTURE_PATH, stabilized_frame)

                region = detect_plate_region(stabilized_frame)
                if region is None:
                    print('  [YOLO] No plate in frame after stabilization — skipping')
                    lcd_standby(lcd)
                    prev_frame = get_lores_gray(picam2)
                    continue

                plate = run_ocr(region)
                if not plate:
                    print("  [WARN] OCR returned nothing usable.")
                    lcd_standby(lcd)
                    prev_frame = get_lores_gray(picam2)
                    continue

                print(f"  [PLATE] Detected: {plate}")

                # Trigger background zone burst
                #start_capture_burst()

                result = lookup_plate(plate)

                if not result:
                    # ── DENIED ──
                    print(f"  [DENIED] Plate '{plate}' not in whitelist.")
                    update_heartbeat("denied")
                    log_entry(plate, "UNKNOWN", "UNKNOWN", None)
                    lcd_denied(lcd, plate)
                    time.sleep(3)
                    lcd_standby(lcd)

                else:
                    owner, role, faculty = result
                    print(f"  [AUTH] {owner} | {role} | {faculty}")

                    slot_id, zone_used = find_slot(faculty, role)

                    if slot_id is None:
                        # ── FULL ──
                        print("  [FULL] No slots available — gate stays closed.")
                        update_heartbeat("full")
                        lcd_full(lcd)
                        time.sleep(3)
                        lcd_standby(lcd)

                    else:
                        # ── GRANTED ──
                        update_heartbeat("granted")
                        assign_slot(slot_id, plate, faculty)
                        log_entry(plate, owner, faculty, slot_id)
                        overflow_note = f" (overflow → Zone {zone_used})" if zone_used != FACULTY_GROUP[faculty] else ""
                        print(f"  [SLOT] Assigned Slot {slot_id}{overflow_note}")
                        print(f"  [GATE] Opening gate for {owner}...")

                        open_gate(pwm)
                        lcd_granted(lcd, owner, slot_id, zone_used)
                        time.sleep(GATE_OPEN_SEC)

                        print("  [GATE] Closing gate.")
                        close_gate(pwm)
                        time.sleep(1)
                        lcd_standby(lcd)

                # Refresh the lores reference frame after handling this
                # detection so the next motion check compares against
                # current conditions, not the pre-detection frame.
                prev_frame = get_lores_gray(picam2)
                time.sleep(0.05)
                continue

            prev_frame = curr_frame
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n\nStopped by user.")
    finally:
        update_heartbeat("offline")
        lcd.clear()
        lcd_standby(lcd)
        pwm.stop()
        picam2.stop()
        GPIO.cleanup()
        print("Cleanup done. Bye!")


if __name__ == "__main__":
    main()
