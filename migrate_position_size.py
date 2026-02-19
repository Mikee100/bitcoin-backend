"""Migration script to add position_size_pct column to existing virtual_account table."""
import sqlite3
import os

DB_PATH = "./signals.db"

if os.path.exists(DB_PATH):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if column exists
    cursor.execute("PRAGMA table_info(virtual_account)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if "position_size_pct" not in columns:
        print("Adding position_size_pct column to virtual_account table...")
        cursor.execute("ALTER TABLE virtual_account ADD COLUMN position_size_pct REAL DEFAULT 100.0")
        conn.commit()
        print("Migration completed successfully!")
    else:
        print("Column position_size_pct already exists.")
    
    # Update any NULL values to 100.0
    cursor.execute("UPDATE virtual_account SET position_size_pct = 100.0 WHERE position_size_pct IS NULL")
    conn.commit()
    
    conn.close()
    print("Migration check completed.")
else:
    print("Database file not found. It will be created on first run.")
