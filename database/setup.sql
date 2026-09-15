CREATE TABLE whitelist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plate TEXT NOT NULL UNIQUE,
    owner_name TEXT NOT NULL,
    role TEXT CHECK(role IN ('Lecturer', 'Non-Academic Staff')),
    faculty TEXT CHECK(faculty IN ('Medicine', 'Computing', 'Non-Academic')),
    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE parking_slots (
    slot_id INTEGER PRIMARY KEY,
    zone TEXT CHECK(zone IN ('A', 'B', 'C')),
    faculty TEXT CHECK(faculty IN ('Medicine', 'Computing', 'Non-Academic')),
    is_occupied INTEGER DEFAULT 0,
    plate TEXT DEFAULT NULL
);

CREATE TABLE entry_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plate TEXT NOT NULL,
    owner_name TEXT,
    faculty TEXT,
    action TEXT CHECK(action IN ('entry', 'exit')),
    slot_id INTEGER,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO parking_slots (slot_id, zone, faculty) VALUES 
    (1, 'A', 'Medicine'),
    (2, 'A', 'Medicine'),
    (3, 'A', 'Medicine'),
    (4, 'B', 'Computing'),
    (5, 'B', 'Computing'),
    (6, 'B', 'Computing'),
    (7, 'C', 'Non-Academic'),
    (8, 'C', 'Non-Academic'),
    (9, 'C', 'Non-Academic');

INSERT INTO whitelist (plate, owner_name, role, faculty) VALUES
    ('CAB-1234', 'Dr. Perera', 'Lecturer', 'Medicine'),
    ('CAB-5678', 'Dr. Silva', 'Lecturer', 'Computing'),
    ('CAB-9012', 'Mr. Fernando', 'Non-Academic Staff', 'Non-Academic');

