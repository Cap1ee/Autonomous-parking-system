import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'parking.db')

def setup_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Whitelist table - authorized vehicles
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS whitelist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number TEXT UNIQUE NOT NULL,
            owner_name TEXT NOT NULL,
            department TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Parking slots table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS parking_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_number TEXT UNIQUE NOT NULL,
            is_occupied INTEGER DEFAULT 0,
            occupied_by TEXT DEFAULT NULL
        )
    ''')

    # Entry/exit log table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number TEXT NOT NULL,
            owner_name TEXT NOT NULL,
            department TEXT NOT NULL,
            slot_assigned TEXT DEFAULT NULL,
            entry_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            exit_time TIMESTAMP DEFAULT NULL,
            access_granted INTEGER NOT NULL
        )
    ''')

    conn.commit()
    conn.close()
    print("Database created successfully!")

if __name__ == '__main__':
    setup_database()
