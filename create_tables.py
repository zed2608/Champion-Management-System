import bcrypt
from database import get_connection
import datetime

def setup_database():
    conn = get_connection()
    if not conn:
        print("Failed to connect to the database. Check your .env file.")
        return

    cursor = conn.cursor()

    print("Creating 'user' table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user (
            user_id INT AUTO_INCREMENT PRIMARY KEY,
            employee_id VARCHAR(50) UNIQUE,
            full_name VARCHAR(100),
            email VARCHAR(100) UNIQUE,
            role VARCHAR(50),
            password_hash VARCHAR(255),
            status VARCHAR(50) DEFAULT 'Active',
            failed_attempts INT DEFAULT 0,
            reset_requested TINYINT(1) DEFAULT 0
        )
    """)

    print("Creating 'tool' table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tool (
            tool_id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100),
            description TEXT,
            category VARCHAR(100),
            supplier VARCHAR(100),
            location VARCHAR(100),
            item_type VARCHAR(50) DEFAULT 'Equipment',
            unit_of_measure VARCHAR(20) DEFAULT 'pcs',
            `condition` VARCHAR(50) DEFAULT 'Good',
            tag_id VARCHAR(100) UNIQUE,
            is_archived TINYINT(1) DEFAULT 0,
            archived_at DATETIME,
            date_acquired DATETIME,
            price DECIMAL(10,2) DEFAULT 0.00
        )
    """)

    print("Creating 'inventory' table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            inventory_id INT AUTO_INCREMENT PRIMARY KEY,
            tool_id INT,
            quantity_total DECIMAL(10,2) DEFAULT 0,
            quantity_available DECIMAL(10,2) DEFAULT 0,
            minimum_stock DECIMAL(10,2) DEFAULT 0,
            FOREIGN KEY (tool_id) REFERENCES tool(tool_id) ON DELETE CASCADE
        )
    """)

    print("Creating 'projects' table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            project_id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255),
            client VARCHAR(255),
            location VARCHAR(255),
            project_head VARCHAR(255),
            start_date DATE,
            end_date DATE,
            description TEXT,
            workers_assigned TEXT,
            tools_needed TEXT,
            approved_by INT,
            manager_id INT,
            status VARCHAR(50) DEFAULT 'Pending',
            is_archived TINYINT(1) DEFAULT 0
        )
    """)

    print("Creating 'transaction' table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transaction (
            transaction_id INT AUTO_INCREMENT PRIMARY KEY,
            tool_id INT,
            user_id INT,
            project_id INT,
            type VARCHAR(50),
            purpose VARCHAR(255),
            borrow_date DATETIME,
            return_date DATETIME,
            status VARCHAR(50) DEFAULT 'Active',
            condition_at_borrow VARCHAR(100),
            condition_at_return VARCHAR(100),
            issued_by INT,
            received_by INT,
            FOREIGN KEY (tool_id) REFERENCES tool(tool_id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES user(user_id) ON DELETE CASCADE,
            FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE SET NULL
        )
    """)
    
    print("Creating 'project_requirements' table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS project_requirements (
            requirement_id INT AUTO_INCREMENT PRIMARY KEY,
            project_id INT,
            tool_id INT,
            quantity DECIMAL(10,2),
            FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
            FOREIGN KEY (tool_id) REFERENCES tool(tool_id) ON DELETE CASCADE
        )
    """)

    # Create Default Admin Account
    current_year = datetime.datetime.now().year
    admin_id = f"ADM-{current_year}-001"
    
    cursor.execute("SELECT * FROM user WHERE role = 'Admin'")
    if not cursor.fetchone():
        print("Inserting default Admin account...")
        default_password = bcrypt.hashpw('admin123'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute(
            "INSERT INTO user (employee_id, full_name, email, role, password_hash) VALUES (%s, %s, %s, %s, %s)",
            (admin_id, 'System Administrator', 'admin@champion.com', 'Admin', default_password)
        )
        print(f"\n✅ Default Admin created!\n   Username: {admin_id}\n   Password: admin123\n")
    else:
        print("✅ Admin account already exists.")

    conn.commit()
    cursor.close()
    conn.close()
    print("Database schema successfully generated!")

if __name__ == "__main__":
    setup_database()