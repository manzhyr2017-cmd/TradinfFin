
import sqlite3
import os

db_path = r"c:\Projects\Trading\titan_bot\data\titan_main.db"

def check_db():
    if not os.path.exists(db_path):
        print(f"File not found: {db_path}")
        return
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"Tables in {db_path}: {tables}")
        
        for table_map in tables:
            table_name = table_map[0]
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            print(f"- Table '{table_name}' has {count} rows.")
            
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_db()
