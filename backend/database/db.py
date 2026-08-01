import sqlite3

DB_NAME = r"C:\Users\user\Documents\GPU_AGGREGATE\backend\database\gpu_catalog.db"


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def create_database():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gpu_catalog (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            provider TEXT NOT NULL,

            gpu_id TEXT NOT NULL UNIQUE,
            gpu_name TEXT NOT NULL,

            manufacturer TEXT,

            vram_gb INTEGER,
            ram_gb INTEGER,
            cpu INTEGER,
            gpu_count INTEGER,

            hourly_price REAL,
            community_price REAL,
            secure_price REAL,
            spot_price REAL,

            availability TEXT,

            deployable INTEGER,

            reliability REAL,

            updated_at TEXT
        );
        """)

    conn.commit()
    conn.close()

    print("Database initialized successfully.")


# if __name__ == "__main__":
#     create_database()