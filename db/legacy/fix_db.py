import mysql.connector
from database import get_connection

def fix_database():
    conn = get_connection()
    if not conn:
        print("Failed to connect to the database.")
        return
    
    cursor = conn.cursor()
    try:
        print("Adding project_id to transaction table...")
        cursor.execute("ALTER TABLE transaction ADD COLUMN project_id INT NULL;")
        
        print("Adding foreign key constraint...")
        cursor.execute("ALTER TABLE transaction ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);")
        
        conn.commit()
        print("✅ Database successfully fixed! You can now run main.py")
        
    except mysql.connector.Error as err:
        if err.errno == 1060: # Error code for Duplicate column name
            print("✅ Column already exists! You are good to go.")
        else:
            print(f"Error: {err}")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    fix_database()