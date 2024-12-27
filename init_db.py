# init_db.py

import sqlite3
import os

def init_db():
    # Define the path to your SQLite database
    db_path = os.path.join(os.path.dirname(__file__), 'refinance_chatbot.db')
    
    # Connect to SQLite (it will create the database file if it doesn't exist)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create the users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            wa_id TEXT PRIMARY KEY,
            state TEXT,
            data TEXT,
            additional_questions INTEGER DEFAULT 0,
            last_interaction DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # (Optional) Create questions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wa_id TEXT,
            question TEXT,
            answer TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (wa_id) REFERENCES users (wa_id)
        )
    ''')
    
    # Commit changes and close the connection
    conn.commit()
    conn.close()
    print("Database and tables initialized successfully.")

if __name__ == "__main__":
    init_db()
