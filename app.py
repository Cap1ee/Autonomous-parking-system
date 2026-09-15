"""
KDU SmartPark — Flask Dashboard
Run with: python3 app.py
Access from any device on the LAN at: http://192.168.1.92:5000
"""

from flask import Flask, render_template, jsonify, request
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)

DB_PATH = os.path.expanduser("~/smartparking/database/parking.db")
CAPTURE_PATH = os.path.expanduser("~/smartparking/static/capture.jpg")
PLATE_CROP_PATH = os.path.expanduser("~/smartparking/static/plate_crop.jpg")

ZONE_CAMERA_PATHS = {
    "zone-a": os.path.expanduser("~/smartparking/static/zone_a_check.jpg"),
    "zone-b": os.path.expanduser("~/smartparking/static/zone_b_check.jpg"),
    "zone-c": os.path.expanduser("~/smartparking/static/zone_c_check.jpg"),
}

HEARTBEAT_TIMEOUT_SEC = 15

FACULTIES = ["Medicine", "Computing", "Non-Academic"]


def get_db():
    """Opens a new DB connection with row access by column name."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


# ----------------------------------------------------------------
# Page routes
# ----------------------------------------------------------------

@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/whitelist")
def whitelist_page():
    return render_template("whitelist.html", faculties=FACULTIES)


# ----------------------------------------------------------------
# API: status (slots + log + capture + heartbeat) — polled every ~3s
# ----------------------------------------------------------------

@app.route("/api/status")
def api_status():
    conn = get_db()

    slots = conn.execute(
        "SELECT slot_id, zone, faculty, is_occupied, plate FROM parking_slots ORDER BY slot_id"
    ).fetchall()

    log = conn.execute(
        "SELECT plate, owner_name, faculty, action, slot_id, timestamp "
        "FROM entry_log ORDER BY id DESC LIMIT 15"
    ).fetchall()

    heartbeat_row = conn.execute(
        "SELECT last_heartbeat, anpr_state FROM system_status WHERE id = 1"
    ).fetchone()

    conn.close()

    is_online = False
    anpr_state = "unknown"
    if heartbeat_row and heartbeat_row["last_heartbeat"]:
        anpr_state = heartbeat_row["anpr_state"] or "unknown"
        try:
            last_seen = datetime.fromisoformat(heartbeat_row["last_heartbeat"])
            elapsed = (datetime.now() - last_seen).total_seconds()
            is_online = elapsed < HEARTBEAT_TIMEOUT_SEC
        except (ValueError, TypeError):
            is_online = False

    capture_mtime = None
    if os.path.exists(CAPTURE_PATH):
        capture_mtime = int(os.path.getmtime(CAPTURE_PATH))

    return jsonify({
        "slots": [dict(s) for s in slots],
        "log": [dict(l) for l in log],
        "anpr_online": is_online,
        "anpr_state": anpr_state,
        "capture_timestamp": capture_mtime,
    })


# ----------------------------------------------------------------
# API: latest zone camera snapshots (filenames match esp32_cameras.py's
# fetch_all_zones() output — zone_a_check.jpg / zone_b_check.jpg / zone_c_check.jpg)
# ----------------------------------------------------------------

@app.route("/api/zone-captures")
def api_zone_captures():
    result = {}
    for zone, path in ZONE_CAMERA_PATHS.items():
        result[zone] = int(os.path.getmtime(path)) if os.path.exists(path) else None
    return jsonify(result)


# ----------------------------------------------------------------
# API: manually free a slot
# ----------------------------------------------------------------

@app.route("/api/slots/<int:slot_id>/free", methods=["POST"])
def api_free_slot(slot_id):
    conn = get_db()
    slot = conn.execute(
        "SELECT plate, faculty FROM parking_slots WHERE slot_id = ?", (slot_id,)
    ).fetchone()

    if slot is None:
        conn.close()
        return jsonify({"error": "Slot not found"}), 404

    if not slot["plate"]:
        conn.close()
        return jsonify({"error": "Slot is already free"}), 400

    plate = slot["plate"]

    conn.execute(
        "UPDATE parking_slots SET is_occupied = 0, plate = NULL WHERE slot_id = ?",
        (slot_id,)
    )
    conn.execute(
        "INSERT INTO entry_log (plate, owner_name, faculty, action, slot_id, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (plate, "Manual Override", slot["faculty"], "exit", slot_id,
         datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

    return jsonify({"success": True, "slot_id": slot_id})


# ----------------------------------------------------------------
# API: whitelist management
# ----------------------------------------------------------------

@app.route("/api/whitelist", methods=["GET"])
def api_whitelist_list():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, plate, owner_name, role, faculty, registered_at "
        "FROM whitelist ORDER BY registered_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/whitelist", methods=["POST"])
def api_whitelist_add():
    data = request.get_json(force=True)

    plate = (data.get("plate") or "").strip().upper()
    owner_name = (data.get("owner_name") or "").strip()
    role = (data.get("role") or "").strip()
    faculty = (data.get("faculty") or "").strip()

    if not plate or not owner_name or not faculty:
        return jsonify({"error": "Plate, owner name, and faculty are required"}), 400

    if faculty not in FACULTIES:
        return jsonify({"error": f"Faculty must be one of {FACULTIES}"}), 400

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO whitelist (plate, owner_name, role, faculty, registered_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (plate, owner_name, role, faculty, datetime.now().isoformat())
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.close()
        msg = str(e)
        if "UNIQUE" in msg:
            return jsonify({"error": f"Plate {plate} is already registered"}), 409
        elif "CHECK" in msg:
            return jsonify({"error": "Invalid role or faculty value"}), 400
        else:
            return jsonify({"error": "Database constraint violation"}), 400

    conn.close()
    return jsonify({"success": True})

@app.route("/api/whitelist/<int:entry_id>", methods=["DELETE"])
def api_whitelist_delete(entry_id):
    conn = get_db()
    cur = conn.execute("DELETE FROM whitelist WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        return jsonify({"error": "Entry not found"}), 404

    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
